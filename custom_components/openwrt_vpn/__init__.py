"""OpenWrt VPN Controller integration."""
import ssl

from .api import AuthenticationError, ControllerError, UbusClient, tls_context
from .const import PLATFORMS


async def async_setup_entry(hass, entry):
    from homeassistant.const import EVENT_HOMEASSISTANT_STOP
    from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    from .coordinator import ControllerCoordinator

    demo = client = None
    try:
        if entry.data.get("demo") is True:
            from .demo.runtime import async_start_demo
            demo = await async_start_demo(hass, entry)
            credentials = demo.lab.credentials
            client = UbusClient(async_get_clientsession(hass), demo.endpoint,
                                credentials["username"], credentials["password"], demo.client_context)
        else:
            context = await hass.async_add_executor_job(tls_context, entry.data.get("ca_pem", ""))
            client = UbusClient(async_get_clientsession(hass), entry.data["endpoint"],
                                entry.data["username"], entry.data["password"], context)
        capabilities = await client.read("capabilities")
        if not isinstance(capabilities, dict) or capabilities.get("api_version") != 1:
            raise ControllerError("Unsupported controller protocol")
        if capabilities.get("controller_id") != entry.unique_id:
            raise ControllerError("Controller identity changed")
        coordinator = ControllerCoordinator(hass, entry, client, capabilities)
        coordinator.demo = demo
        await coordinator.load_cursor()
        await coordinator.async_config_entry_first_refresh()
        entry.runtime_data = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException as err:
        if client is not None:
            await client.close()
        if demo is not None:
            await demo.close()
        if isinstance(err, AuthenticationError):
            raise ConfigEntryAuthFailed("RPC authentication failed") from err
        if isinstance(err, (ControllerError, ssl.SSLError, ValueError, KeyError, OSError)):
            raise ConfigEntryNotReady("Cannot initialize verified controller connection") from err
        raise
    if demo is not None:
        async def stop_demo(event):
            await demo.close()
        entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop_demo))
    entry.async_on_unload(entry.add_update_listener(_update_options))
    return True


async def _update_options(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.client.close()
        if entry.runtime_data.demo is not None:
            await entry.runtime_data.demo.close()
        return True
    return False
