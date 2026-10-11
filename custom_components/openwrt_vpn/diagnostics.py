"""No endpoint, username, password, session or CA from config entries is exported."""
async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = entry.runtime_data
    return {"capabilities": coordinator.capabilities, "snapshot": coordinator.data,
            "recent_events": coordinator.events}
