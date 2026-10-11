"""Real HTTPS fixtures; Home Assistant itself is not mocked."""
import asyncio
from pathlib import Path
import ssl

from aiohttp import ClientSession, web
import pytest
import pytest_asyncio

from simulator.engine import Controller
from simulator.server import APP_KEY, create_app
from tools.create_lab import create_lab


@pytest_asyncio.fixture
async def lab_factory(tmp_path):
    import json
    runners = []

    async def start(autonomous=False, folder=None, include_ip=True):
        folder = folder or tmp_path / f"lab-{len(runners)}"
        create_lab(folder, include_ip=include_ip)
        credentials = json.loads((folder / "credentials.json").read_text())
        controller = Controller(folder / "controller.json")
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(folder / "server.pem", folder / "server.key")
        app = create_app(controller, credentials, autonomous=autonomous)
        app[APP_KEY].sample()
        controller.tick()
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=ctx)
        await site.start()
        runners.append(runner)
        return {
            "engine": controller, "lab": app[APP_KEY], "credentials": credentials,
            "ca": (folder / "ca.pem").read_text(), "folder": folder,
            "endpoint": f"https://127.0.0.1:{runner.addresses[0][1]}/ubus",
        }

    yield start
    for runner in runners:
        await runner.cleanup()


@pytest_asyncio.fixture
async def lab(lab_factory):
    return await lab_factory()


@pytest_asyncio.fixture
async def client(lab):
    from custom_components.openwrt_vpn.api import UbusClient, tls_context
    async with ClientSession() as session:
        c = UbusClient(session, lab["endpoint"], lab["credentials"]["username"],
                       lab["credentials"]["password"], tls_context(lab["ca"]))
        yield c
        await c.close()


@pytest.fixture
def root():
    return Path(__file__).resolve().parents[1]


@pytest_asyncio.fixture
async def hass(tmp_path, root, lab_factory):
    import shutil
    from homeassistant import bootstrap, loader
    from homeassistant.core import HomeAssistant
    config_dir = tmp_path / "ha"
    config_dir.mkdir()
    shutil.copytree(root / "custom_components", config_dir / "custom_components",
                    ignore=shutil.ignore_patterns("__pycache__"))
    instance = HomeAssistant(str(config_dir))
    loader.async_setup(instance)
    instance.config.skip_pip = True
    instance.config.skip_pip_packages = set()
    try:
        from homeassistant.config_entries import ConfigEntries
        from homeassistant.setup import async_setup_component
        instance.config_entries = ConfigEntries(instance, {})
        await loader.async_get_custom_components(instance)
        assert await asyncio.wait_for(bootstrap.async_load_base_functionality(instance), 60)
        assert await async_setup_component(instance, "homeassistant", {})
        assert await async_setup_component(instance, "persistent_notification", {})
        assert await async_setup_component(instance, "network", {})
        await instance.async_start()
        yield instance
    finally:
        await instance.async_stop(force=True)
