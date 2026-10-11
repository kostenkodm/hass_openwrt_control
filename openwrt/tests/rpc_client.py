"""Actual HTTPS uhttpd/rpcd/ubus/ucode/Podkop/sing-box integration test."""

import asyncio
import json
from pathlib import Path
import ssl

from aiohttp import ClientSession
from custom_components.openwrt_vpn.api import AuthenticationError, ControllerError, UbusClient, tls_context


async def main():
    folder = Path("work/native-tls")
    credentials = json.loads((folder / "credentials.json").read_text())
    async with ClientSession() as session:
        client = UbusClient(
            session,
            "https://127.0.0.1:18443/ubus",
            credentials["username"],
            credentials["password"],
            tls_context((folder / "server.pem").read_text()),
        )
        caps = await client.read("capabilities")
        assert caps["controller_kind"] == "openwrt_ucode" and caps["simulated"] is False
        state = await client.read("status")
        assert state["sections"]["main"]["applied_vpn"] == "vpn_b"
        result = await client.mutate("assign_vpn", {"section_id": "main", "vpn": "vpn_a"}, state["revision"])
        assert result["status"] == "completed", result
        assert (await client.read("status"))["sections"]["main"]["applied_vpn"] == "vpn_a"
        print("PASS actual HA client HTTPS → rpcd ACL → native Podkop assignment")
        before = await client.read("status")
        result = await client.mutate("restart_vpn", {"vpn": "vpn_a"}, before["revision"])
        assert result["status"] == "completed", result
        after = await client.read("status")
        assert {sid: s["applied_vpn"] for sid, s in before["sections"].items()} == {
            sid: s["applied_vpn"] for sid, s in after["sections"].items()
        }
        assert {sid: s["policy"] for sid, s in before["sections"].items()} == {
            sid: s["policy"] for sid, s in after["sections"].items()
        }
        counts = json.loads(Path("work/native-rootfs/tmp/restart-vpn_a.json").read_text())
        assert counts == {"down": 1, "up": 1}, counts
        for vpn in ["inbound_vpn", "wan", "vpn_a;reboot"]:
            try:
                await client.mutate("restart_vpn", {"vpn": vpn}, after["revision"])
            except ControllerError:
                continue
            raise AssertionError("Forbidden restart accepted")
        assert not Path("work/native-rootfs/tmp/restart-inbound_vpn.json").exists()
        print("PASS limited restart through HTTPS; protected targets denied; policies unchanged")

        for obj, method in [
            ("uci", "get"),
            ("uci", "set"),
            ("file", "exec"),
            ("service", "list"),
            ("rc", "init"),
            ("network.interface.wan", "down"),
            ("system", "reboot"),
        ]:
            try:
                await client._rpc(client._sid, obj, method, {})
            except AuthenticationError:
                continue
            raise AssertionError(f"Privilege was not denied: {obj}.{method}")
        print("PASS real rpcd denies generic UCI, shell, service, network and reboot rights")
        try:
            invalid = UbusClient(
                session,
                client.endpoint,
                credentials["username"],
                credentials["password"],
                ssl.create_default_context(),
            )
            await invalid.read("status")
        except ControllerError:
            pass
        else:
            raise AssertionError("Untrusted TLS certificate accepted")
        print("PASS server certificate trust is required")
        await client.close()


asyncio.run(main())
