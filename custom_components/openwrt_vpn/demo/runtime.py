"""Explicit, isolated HA demo; all controller calls still use verified HTTPS."""
from dataclasses import dataclass, field
import json
from pathlib import Path
import ssl

from aiohttp import web

from ..api import ControllerError, tls_context
from .certificates import create_lab
from .engine import Controller
from .server import APP_KEY, create_app

SCENARIOS = ("vpn_a_down", "all_down", "recover", "verify_failure")


def prepare(folder, controller_id):
    create_lab(folder)
    controller = Controller(folder / "controller.json", controller_id=controller_id)
    if controller.data["controller_id"] != controller_id:
        raise ControllerError("Stored demo identity does not match this entry")
    credentials = json.loads((folder / "credentials.json").read_text())
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.minimum_version = ssl.TLSVersion.TLSv1_2
    server_context.load_cert_chain(folder / "server.pem", folder / "server.key")
    client_context = tls_context((folder / "ca.pem").read_text())
    return controller, credentials, server_context, client_context


@dataclass(repr=False)
class DemoRuntime:
    runner: web.AppRunner
    lab: object
    endpoint: str
    client_context: ssl.SSLContext = field(repr=False)
    closed: bool = False

    async def close(self):
        if not self.closed:
            self.closed = True
            await self.runner.cleanup()

    async def scenario(self, hass, scenario):
        if scenario not in SCENARIOS:
            raise ValueError("Unknown demo scenario")
        async with self.lab.lock:
            await hass.async_add_executor_job(self._scenario, scenario)

    def _scenario(self, scenario):
        if scenario == "verify_failure":
            self.lab.controller.fault = "verify"
            return
        self.lab.controller.fault = None
        for vpn, probe in self.lab.probes.items():
            passed = scenario == "recover" or (scenario == "vpn_a_down" and vpn != "vpn_a")
            probe.update(successes=3 if passed else 0, egress=passed)
        for _ in range(self.lab.controller.data["settings"]["failure_cycles"]):
            self.lab.sample_and_tick()


async def async_start_demo(hass, entry):
    folder = Path(hass.config.path(".storage", "openwrt_vpn_demo", entry.entry_id))
    controller, credentials, server_context, client_context = await hass.async_add_executor_job(
        prepare, folder, entry.unique_id)
    app = create_app(controller, credentials)
    runner = web.AppRunner(app, access_log=None)
    try:
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0, ssl_context=server_context).start()
        lab = app[APP_KEY]
        async with lab.lock:
            await hass.async_add_executor_job(lab.sample_and_tick)
        return DemoRuntime(runner, lab, f"https://127.0.0.1:{runner.addresses[0][1]}/ubus", client_context)
    except BaseException:
        await runner.cleanup()
        raise
