"""End-to-end tests against actual Home Assistant Core 2026.10.1."""
from copy import deepcopy

from custom_components.openwrt_vpn.api import ControllerError
from custom_components.openwrt_vpn.const import DOMAIN
from homeassistant.helpers import entity_registry as er


async def add_controller(hass, lab):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"},
        data={"endpoint": lab["endpoint"], "username": lab["credentials"]["username"],
              "password": lab["credentials"]["password"], "ca_pem": lab["ca"]},
    )
    assert result["type"] == "create_entry", result
    await hass.async_block_till_done()
    entry = result["result"]
    assert entry.runtime_data.data["controller_id"] == lab["engine"].data["controller_id"]
    return entry


def entity_id(hass, entry, platform, group, resource, key):
    return er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{entry.unique_id}:{group}:{resource}:{key}"
    )


async def test_config_flow_all_platforms_and_policy_control(hass, lab):
    entry = await add_controller(hass, lab)
    c = entry.runtime_data
    entities = [e for e in er.async_get(hass).entities.values() if e.config_entry_id == entry.entry_id]
    assert len(entities) == 55
    assert {e.domain for e in entities} == {"sensor", "binary_sensor", "select", "switch", "button"}
    assert not any("inbound_vpn" in e.unique_id for e in entities)
    import json
    from pathlib import Path
    Path("work/ha-entity-map.json").write_text(json.dumps([
        {"entity_id": e.entity_id, "unique_id": e.unique_id} for e in entities
    ], indent=2))
    selection = entity_id(hass, entry, "select", "sections", "main", "policy")
    assert hass.states.get(selection).state == "vpn_a"
    await hass.services.async_call("select", "select_option",
                                  {"entity_id": selection, "option": "Auto"}, blocking=True)
    assert c.data["sections"]["main"]["policy"]["mode"] == "auto"
    assert c.data["sections"]["main"]["applied_vpn"] == "vpn_a"
    switch = entity_id(hass, entry, "switch", "controller", "controller", "automation")
    await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
    assert c.data["automation"] is True
    button = entity_id(hass, entry, "button", "controller", "controller", "diagnose")
    await hass.services.async_call("button", "press", {"entity_id": button}, blocking=True)
    assert c.data["vpns"]["vpn_a"]["http_test"] is True
    await hass.services.async_call("switch", "turn_off", {"entity_id": switch}, blocking=True)
    assert c.data["sections"]["main"]["applied_vpn"] == "vpn_a"


async def test_options_flow_controls_simulator_and_section(hass, lab):
    entry = await add_controller(hass, lab)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "menu"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "general"})
    assert result["step_id"] == "general"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        "run_mode": "control", "poll_interval": 30, "probe_interval": 60,
        "failure_cycles": 3, "quorum": 2, "min_hold": 600,
    })
    assert result["type"] == "create_entry", result
    await hass.async_block_till_done()
    assert entry.runtime_data.data["run_mode"] == "control"
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "section"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"section_id": "main"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        "mode": "auto", "vpn": "vpn_a", "candidates": "vpn_b, vpn_a",
        "algorithm": "quality", "return_policy": "sticky", "quality_margin": 7, "preferences": '{"vpn_b": 3}',
    })
    assert result["type"] == "create_entry", result
    await hass.async_block_till_done()
    policy = entry.runtime_data.data["sections"]["main"]["policy"]
    assert policy["candidates"] == ["vpn_b", "vpn_a"]
    assert policy["preferences"] == {"vpn_b": 3}


async def test_bad_credentials_and_duplicate_controller(hass, lab):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"},
        data={"endpoint": lab["endpoint"], "username": "hass", "password": "wrong", "ca_pem": lab["ca"]})
    assert result["errors"] == {"base": "invalid_auth"}
    await add_controller(hass, lab)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"},
        data={"endpoint": lab["endpoint"], **{k: lab["credentials"][k] for k in ("username", "password")},
              "ca_pem": lab["ca"]})
    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"


async def test_discovery_addition_and_removal(hass, lab):
    entry = await add_controller(hass, lab)
    c, engine = entry.runtime_data, lab["engine"]
    engine.data["vpns"]["extra_vpn"] = {"id": "extra_vpn", "approved": True, "name": "Extra"}
    engine.record_probe("extra_vpn")
    extra = deepcopy(engine.data["sections"]["main"])
    extra.update(id="extra_section", name="Extra section")
    engine.data["sections"]["extra_section"] = extra
    await c.async_refresh()
    await hass.async_block_till_done()
    ident = entity_id(hass, entry, "select", "sections", "extra_section", "policy")
    assert ident and hass.states.get(ident)
    assert entity_id(hass, entry, "sensor", "vpns", "extra_vpn", "latency_ms")
    del engine.data["sections"]["extra_section"]
    del engine.data["vpns"]["extra_vpn"]
    await c.async_refresh()
    await hass.async_block_till_done()
    assert entity_id(hass, entry, "select", "sections", "extra_section", "policy") is None
    assert hass.states.get(ident) is None


async def test_connection_events_are_transitions(hass, lab, monkeypatch):
    entry = await add_controller(hass, lab)
    c, events = entry.runtime_data, []
    unsubscribe = hass.bus.async_listen(f"{DOMAIN}_event", lambda event: events.append(event.data))
    original = c.client.read

    async def failure(*args, **kwargs):
        raise ControllerError("Simulated outage")
    monkeypatch.setattr(c.client, "read", failure)
    await c.async_refresh()
    await c.async_refresh()
    await hass.async_block_till_done()
    status = entity_id(hass, entry, "binary_sensor", "controller", "controller", "controller_available")
    latency = entity_id(hass, entry, "sensor", "vpns", "vpn_a", "latency_ms")
    assert hass.states.get(status).state == "off"
    assert hass.states.get(latency).state == "unavailable"
    assert len([e for e in events if e["type"] == "controller_lost"]) == 1
    monkeypatch.setattr(c.client, "read", original)
    await c.async_refresh()
    await hass.async_block_till_done()
    assert len([e for e in events if e["type"] == "controller_restored"]) == 1
    assert hass.states.get(status).state == "on"
    unsubscribe()


async def test_two_controllers_are_independent(hass, lab, lab_factory):
    first = await add_controller(hass, lab)
    other = await lab_factory()
    second = await add_controller(hass, other)
    first_switch = entity_id(hass, first, "switch", "controller", "controller", "automation")
    second_switch = entity_id(hass, second, "switch", "controller", "controller", "automation")
    assert first_switch != second_switch
    await hass.services.async_call("switch", "turn_on", {"entity_id": first_switch}, blocking=True)
    assert first.runtime_data.data["automation"] is True
    assert second.runtime_data.data["automation"] is False


async def test_diagnostics_exclude_secrets(hass, lab):
    from custom_components.openwrt_vpn.diagnostics import async_get_config_entry_diagnostics
    entry = await add_controller(hass, lab)
    text = repr(await async_get_config_entry_diagnostics(hass, entry))
    for secret in (lab["credentials"]["password"], lab["credentials"]["lab_token"],
                   lab["endpoint"], "BEGIN CERTIFICATE", entry.runtime_data.client._sid):
        assert secret not in text


async def test_event_cursor_survives_entry_reload(hass, lab):
    entry = await add_controller(hass, lab)
    events = []
    unsubscribe = hass.bus.async_listen(f"{DOMAIN}_event", lambda event: events.append(event.data))
    lab["engine"]._event("vpn_failed", vpn="vpn_a")
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert len([e for e in events if e["type"] == "vpn_failed"]) == 1
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await entry.runtime_data.async_refresh()
    assert len([e for e in events if e["type"] == "vpn_failed"]) == 1
    unsubscribe()


async def test_concurrent_commands_and_immediate_snapshot(hass, lab):
    import asyncio
    entry = await add_controller(hass, lab)
    c = entry.runtime_data
    await asyncio.gather(c.command("set_automation", {"enabled": True}), c.command("diagnose", {}))
    assert c.data["automation"] is True
    await c.command("set_automation", {"enabled": False})
    assert c.data["automation"] is False


async def test_blocks_commands_to_unsupported_backend(hass, lab, monkeypatch):
    import pytest
    from homeassistant.exceptions import HomeAssistantError
    entry = await add_controller(hass, lab)
    coordinator = entry.runtime_data
    coordinator.capabilities["simulated"] = False

    async def forbidden(*args, **kwargs):
        raise AssertionError("A write must not be sent")
    monkeypatch.setattr(coordinator.client, "mutate", forbidden)
    with pytest.raises(HomeAssistantError, match="does not support policy commands"):
        await coordinator.command("set_automation", {"enabled": True})
    assert lab["engine"].data["automation"] is False


async def test_observe_exposes_proposed_assignment_without_changing_other_sections(hass, lab):
    entry = await add_controller(hass, lab)
    selection = entity_id(hass, entry, "select", "sections", "main", "policy")
    await hass.services.async_call("select", "select_option",
                                  {"entity_id": selection, "option": "vpn_b"}, blocking=True)
    for key, expected in (("proposed_vpn", "vpn_b"), ("applied_vpn", "vpn_a"),
                          ("application_state", "pending_observe")):
        ident = entity_id(hass, entry, "sensor", "sections", "main", key)
        assert hass.states.get(ident).state == expected
    for section, expected in (("media", "vpn_b"), ("custom", "vpn_c")):
        ident = entity_id(hass, entry, "select", "sections", section, "policy")
        assert hass.states.get(ident).state == expected
    mode = entity_id(hass, entry, "sensor", "controller", "controller", "run_mode")
    assert hass.states.get(mode).attributes["device_class"] == "enum"
    assert lab["engine"].data["automation"] is False


async def test_native_policy_capability_allows_observe_commands(hass, lab):
    entry = await add_controller(hass, lab)
    c = entry.runtime_data
    c.capabilities = {**c.capabilities, "controller_kind": "openwrt_ucode",
                      "simulated": False, "simulation_control": False,
                      "policy_control": True, "production_control": False}
    await c.command("set_automation", {"enabled": True})
    assert c.data["automation"] is True
    sensor = entity_id(hass, entry, "sensor", "vpns", "vpn_a", "last_handshake")
    assert hass.states.get(sensor).attributes["supported"] is False
    button = entity_id(hass, entry, "button", "vpns", "vpn_a", "restart_vpn")
    assert hass.states.get(button).state == "unavailable"
    import pytest
    from homeassistant.exceptions import HomeAssistantError
    with pytest.raises(HomeAssistantError, match="requires control"):
        await c.command("restart_vpn", {"vpn": "vpn_a"})


async def test_restart_button_preserves_policies_and_local_permissions(hass, lab):
    import pytest
    from homeassistant.exceptions import HomeAssistantError
    entry = await add_controller(hass, lab)
    c = entry.runtime_data
    button = entity_id(hass, entry, "button", "vpns", "vpn_a", "restart_vpn")
    assert button and hass.states.get(button).state != "unavailable"
    before = deepcopy(c.data["sections"])
    await hass.services.async_call("button", "press", {"entity_id": button}, blocking=True)
    assert c.data["sections"] == before
    assert lab["engine"].data["events"][-1]["type"] == "vpn_restart_completed"
    assert lab["engine"].data["events"][-1]["simulated"] is True
    lab["engine"].data["vpns"]["vpn_a"]["restart_allowed"] = False
    await c.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(button).state == "unavailable"
    revision = c.data["revision"]
    with pytest.raises(HomeAssistantError, match="not locally permitted"):
        await c.command("restart_vpn", {"vpn": "vpn_a"})
    assert lab["engine"].data["revision"] == revision
