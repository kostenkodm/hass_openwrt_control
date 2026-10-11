"""HACS-contained demo exercised through actual Home Assistant flows and services."""
import json
from pathlib import Path
import ssl

import aiohttp
import pytest
from homeassistant.helpers import device_registry as dr, entity_registry as er

from custom_components.openwrt_vpn.const import DOMAIN


async def add_demo(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == "menu"
    assert result["menu_options"] == ["demo", "controller"]
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "demo"})
    assert result["step_id"] == "demo"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] == "create_entry", result
    await hass.async_block_till_done()
    entry = result["result"]
    assert entry.runtime_data.demo is not None
    return entry


def entity_id(hass, entry, platform, group, resource, key):
    return er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{entry.unique_id}:{group}:{resource}:{key}")


async def scenario(hass, entry, name):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert "demo_scenario" in result["menu_options"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "demo_scenario"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"scenario": name})
    assert result["type"] == "abort" and result["reason"] == "demo_scenario_applied", result


async def test_hacs_demo_flow_entities_tls_and_no_entry_secrets(hass):
    entry = await add_demo(hass)
    assert dict(entry.data) == {"demo": True}
    c = entry.runtime_data
    assert c.data["run_mode"] == "observe" and c.data["automation"] is False
    assert c.demo.endpoint.startswith("https://127.0.0.1:")
    assert c.demo.runner.addresses == [("127.0.0.1", int(c.demo.endpoint.split(":")[2].split("/")[0]))]
    assert c.demo.client_context.verify_mode == ssl.CERT_REQUIRED
    assert c.demo.client_context.check_hostname is True
    entities = [e for e in er.async_get(hass).entities.values() if e.config_entry_id == entry.entry_id]
    assert len(entities) == 52
    assert all(hass.states.get(e.entity_id) is not None for e in entities)
    assert all(hass.states.get(e.entity_id).attributes["simulated"] for e in entities)
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, entry.unique_id), entry.entry_id)
    assert "Demo" in device.name
    from custom_components.openwrt_vpn.diagnostics import async_get_config_entry_diagnostics
    diagnostics = json.dumps(await async_get_config_entry_diagnostics(hass, entry))
    for secret in (c.demo.lab.credentials["password"], c.demo.lab.credentials["lab_token"],
                   c.demo.endpoint, "BEGIN CERTIFICATE", c.client._sid):
        assert secret not in diagnostics
    # The fixture installed ONLY custom_components into the HA config directory.
    assert not Path(hass.config.path("simulator")).exists()
    assert not Path(hass.config.path("tools")).exists()
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "demo"})
    assert result["reason"] == "demo_already_configured"


async def test_demo_observe_manual_failover_and_all_down_scenarios(hass):
    entry = await add_demo(hass)
    c = entry.runtime_data
    selection = entity_id(hass, entry, "select", "sections", "main", "policy")
    await hass.services.async_call("select", "select_option", {"entity_id": selection, "option": "vpn_b"}, blocking=True)
    assert c.data["sections"]["main"]["applied_vpn"] == "vpn_a"
    assert c.data["sections"]["main"]["proposed_vpn"] == "vpn_b"
    await hass.services.async_call("select", "select_option", {"entity_id": selection, "option": "Auto"}, blocking=True)
    await c.command("configure", {"run_mode": "control", "probe_interval": 60,
                                 "failure_cycles": 3, "quorum": 2, "min_hold": 0})
    switch = entity_id(hass, entry, "switch", "controller", "controller", "automation")
    await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
    await scenario(hass, entry, "vpn_a_down")
    assert c.data["sections"]["main"]["applied_vpn"] == "vpn_b"
    assert c.data["sections"]["media"]["policy"]["mode"] == "manual"
    assert c.data["sections"]["media"]["applied_vpn"] == "vpn_b"
    assert c.data["sections"]["custom"]["applied_vpn"] == "vpn_c"
    await scenario(hass, entry, "all_down")
    assert c.data["sections"]["main"]["applied_vpn"] == "vpn_b"
    assert c.data["sections"]["main"]["all_unavailable"] is True
    await scenario(hass, entry, "recover")
    assert c.data["sections"]["main"]["applied_vpn"] == "vpn_a"
    assert c.data["sections"]["main"]["all_unavailable"] is False


async def test_demo_reload_preserves_policy_and_unload_closes_api(hass):
    entry = await add_demo(hass)
    c = entry.runtime_data
    await c.command("assign_vpn", {"section_id": "main", "vpn": "vpn_b"})
    original, identity = c.demo, entry.unique_id
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    c = entry.runtime_data
    assert original.closed
    assert c.demo is not original and c.demo.closed is False
    assert entry.unique_id == identity
    assert c.data["sections"]["main"]["policy"]["vpn"] == "vpn_b"
    assert c.data["sections"]["main"]["applied_vpn"] == "vpn_a"
    demo = c.demo
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert demo.closed and demo.lab.task.done()
    async with aiohttp.ClientSession() as session:
        with pytest.raises(aiohttp.ClientError):
            await session.post(demo.endpoint, json={}, ssl=demo.client_context)


async def test_demo_rollback_scenario(hass):
    entry = await add_demo(hass)
    c = entry.runtime_data
    await c.command("configure", {"run_mode": "control", "probe_interval": 60,
                                 "failure_cycles": 3, "quorum": 2, "min_hold": 600})
    await scenario(hass, entry, "verify_failure")
    selection = entity_id(hass, entry, "select", "sections", "main", "policy")
    from homeassistant.exceptions import HomeAssistantError
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("select", "select_option", {"entity_id": selection, "option": "vpn_b"}, blocking=True)
    assert c.data["sections"]["main"]["applied_vpn"] == "vpn_a"
    assert c.data["sections"]["main"]["application_state"] == "rolled_back"
    assert any(event["type"] == "rolled_back" for event in c.events)


async def test_connected_controller_has_no_embedded_demo_options(hass, lab):
    from tests.test_homeassistant import add_controller
    entry = await add_controller(hass, lab)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["menu_options"] == ["general", "section"]
    assert entry.runtime_data.demo is None
