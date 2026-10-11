"""Run HTTPS RPC scenarios and generate a standalone Russian report."""
import argparse
import asyncio
import html
import json
from pathlib import Path
import ssl

from aiohttp import ClientSession, web
from custom_components.openwrt_vpn.api import UbusClient, tls_context
from simulator.engine import Controller
from simulator.server import APP_KEY, create_app
from tools.create_lab import create_lab


async def run(folder, output):
    create_lab(folder)
    credentials = json.loads((folder / "credentials.json").read_text())
    engine = Controller()
    app = create_app(engine, credentials, autonomous=False)
    lab = app[APP_KEY]
    lab.sample()
    engine.tick()
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(folder / "server.pem", folder / "server.key")
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 0, ssl_context=context).start()
    cases = []
    try:
        async with ClientSession() as session:
            client = UbusClient(session, f"https://127.0.0.1:{runner.addresses[0][1]}/ubus",
                                credentials["username"], credentials["password"],
                                tls_context((folder / "ca.pem").read_text()))

            async def state(label):
                snapshot = await client.read("status")
                cases.append({"step": label, "snapshot": snapshot})

            async def command(method, **values):
                snapshot = await client.read("status")
                return await client.mutate(method, values, snapshot["revision"])

            await state("Начало: observe, автоматика выключена")
            policy = dict(engine.data["sections"]["main"]["policy"], mode="auto")
            await command("set_policy", section_id="main", policy=policy)
            await command("configure", run_mode="control", **engine.data["settings"])
            await command("set_automation", enabled=True)
            await state("main: Auto; media и custom: Manual")
            for _ in range(3):
                engine.record_probe("vpn_a", successes=0, egress=False)
                engine.tick()
            await state("Отказ vpn_a: main → vpn_b; Manual сохранён")
            for _ in range(3):
                for vpn in engine.data["vpns"]:
                    engine.record_probe(vpn, successes=0, egress=False)
                engine.tick()
            await state("Все VPN недоступны: последнее назначение сохранено")
            engine.record_probe("vpn_c")
            engine.tick()
            await state("Восстановление: main → vpn_c")
            engine.record_probe("vpn_b")
            engine.fault = "verify"
            outcome = await command("assign_vpn", section_id="main", vpn="vpn_b")
            assert outcome["status"] == "rolled_back"
            await state("Ошибка проверки применения: выполнен откат")
            await client.close()
    finally:
        await runner.cleanup()
    output.mkdir(parents=True, exist_ok=True)
    (output / "demo.json").write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = []
    for case in cases:
        snapshot = case["snapshot"]
        cells = "".join(f"<td>{html.escape(snapshot['sections'][sid]['applied_vpn'])}</td>"
                        for sid in ("main", "media", "custom"))
        rows.append(f"<tr><th>{html.escape(case['step'])}</th>{cells}</tr>")
    report = """<!doctype html><html lang="ru"><meta charset="utf-8">
<title>OpenWrt VPN — прототип</title><style>
body{font:16px system-ui;max-width:1100px;margin:48px auto;padding:0 24px;background:#101827;color:#e5edf8}
h1{font-size:32px}aside{padding:18px;border:1px solid #e8ae42;border-radius:10px;color:#ffdb8b}
table{border-collapse:collapse;width:100%;margin:32px 0}th,td{text-align:left;padding:16px;border-bottom:1px solid #334155}
td{color:#8ee4d6}p{line-height:1.6}small{color:#afbdd1}</style>
<h1>OpenWrt VPN Controller · прототип 0.1</h1>
<aside>Локальная симуляция. Проверки VPN, внешние IP и применение Podkop смоделированы.
Реальный маршрутизатор не подключался. Отсутствие утечек на OpenWrt ещё не доказано.</aside>
<p>Сценарий выполнен через HTTPS ubus JSON-RPC с проверкой CA и имени сервера.
HA-интеграция содержит политики секций, автоматику, диагностику, метрики и историю.</p>
<table><thead><tr><th>Сценарий</th><th>main</th><th>media</th><th>custom</th></tr></thead><tbody>"""
    report += "".join(rows) + "</tbody></table><small>inbound_vpn исключён из исходящих кандидатов. Результаты относятся к симулятору.</small></html>"
    (output / "demo.html").write_text(report, encoding="utf-8")
    print(f"HTTPS demo complete: {len(cases)} scenarios; report {output / 'demo.html'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab", type=Path, default=Path("work/demo-lab"))
    parser.add_argument("--output", type=Path, default=Path("outputs/prototype"))
    args = parser.parse_args()
    asyncio.run(run(args.lab, args.output))
