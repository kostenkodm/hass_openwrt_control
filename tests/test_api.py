import asyncio
import ssl

from aiohttp import ClientSession
import pytest

from custom_components.openwrt_vpn.api import (
    AuthenticationError, ControllerError, OutcomeUnknown, ProtocolError, RemoteError,
    UbusClient, tls_context,
)
from simulator.server import APP_KEY, create_app


async def test_verified_https_and_authentication(client, lab, caplog):
    status = await client.read("status")
    assert status["controller_id"] == lab["engine"].data["controller_id"]
    assert status["simulated"] is True
    assert lab["credentials"]["password"] not in caplog.text
    assert client._sid not in caplog.text


async def test_wrong_password_rejected(lab):
    async with ClientSession() as session:
        client = UbusClient(session, lab["endpoint"], "hass", "wrong", tls_context(lab["ca"]))
        with pytest.raises(AuthenticationError):
            await client.read("status")


async def test_untrusted_certificate_rejected(lab):
    async with ClientSession() as session:
        client = UbusClient(session, lab["endpoint"], "hass", "wrong", tls_context())
        with pytest.raises(ControllerError):
            await client.read("status")


def test_http_or_disabled_hostname_verification_rejected():
    with pytest.raises(ProtocolError):
        UbusClient(None, "http://router/ubus", "hass", "x", tls_context())
    context = ssl.create_default_context()
    context.check_hostname = False
    with pytest.raises(ProtocolError):
        UbusClient(None, "https://router/ubus", "hass", "x", context)


async def test_expired_session_is_renewed_for_reads(client, lab):
    await client.read("status")
    old_sid = client._sid
    lab["lab"].sessions.clear()
    await client.read("status")
    assert client._sid != old_sid


@pytest.mark.parametrize(("obj", "method"), [
    ("uci", "get"), ("uci", "set"), ("file", "exec"), ("rc", "init"),
    ("service", "delete"), ("network.interface.wan", "down"), ("system", "reboot"),
])
async def test_acl_denies_generic_privileges(client, obj, method):
    await client.read("status")
    with pytest.raises(AuthenticationError):
        await client._rpc(client._sid, obj, method, {})


async def test_client_has_no_generic_write_method(client):
    with pytest.raises(ProtocolError):
        await client.mutate("uci_set", {}, 0)


async def test_extra_arguments_rejected(client):
    state = await client.read("status")
    with pytest.raises(RemoteError) as err:
        await client.mutate("diagnose", {"command": "reboot"}, state["revision"])
    assert err.value.code == "invalid_argument"


async def test_dropped_write_response_is_queried_not_replayed(client, monkeypatch):
    original = client._rpc
    writes = []

    async def dropped(sid, obj, method, args):
        result = await original(sid, obj, method, args)
        if method == "set_automation":
            writes.append(args["request_id"])
            raise ControllerError("Simulated lost response")
        return result
    await client.read("status")
    monkeypatch.setattr(client, "_rpc", dropped)
    result = await client.mutate("set_automation", {"enabled": True}, 0)
    assert result["status"] == "completed"
    assert len(writes) == 1
    assert (await client.read("status"))["automation"] is True


async def test_unknown_write_outcome_is_explicit(client, monkeypatch):
    original = client._rpc
    writes = []

    async def disconnected(sid, obj, method, args):
        if method == "set_automation":
            writes.append(args["request_id"])
            raise ControllerError("Simulated disconnect before reply")
        return await original(sid, obj, method, args)
    await client.read("status")
    monkeypatch.setattr(client, "_rpc", disconnected)
    with pytest.raises(OutcomeUnknown) as err:
        await client.mutate("set_automation", {"enabled": True}, 0)
    assert err.value.request_id == writes[0]
    assert len(writes) == 1


async def test_lab_control_not_available_to_rpc_account(client, lab):
    await client.read("status")
    async with client.session.post(lab["endpoint"].replace("/ubus", "/_lab"),
                                   json={"fault": "rollback"}, ssl=client.context) as result:
        assert result.status == 403


async def test_simulator_runs_without_any_ha_client(lab):
    from copy import deepcopy
    from tests.test_engine import command, control
    c = lab["engine"]
    control(c)
    p = deepcopy(c.data["sections"]["main"]["policy"])
    p["mode"] = "auto"
    command(c, "set_policy", section_id="main", policy=p)
    command(c, "set_automation", enabled=True)
    now = c.clock()
    c.clock = lambda: now  # logical probe time; independent of filesystem latency
    c.data["settings"]["probe_interval"] = .02  # accelerated cycle scheduling
    app = create_app(c, lab["credentials"], autonomous=True)
    laboratory = app[APP_KEY]
    laboratory.probes["vpn_a"] = {"successes": 0, "latency": 100, "egress": False}
    task = asyncio.create_task(laboratory.cycle())
    try:
        async with asyncio.timeout(5):
            while c.data["sections"]["main"]["applied_vpn"] != "vpn_b":
                await asyncio.sleep(.02)
        assert c.data["sections"]["main"]["applied_vpn"] == "vpn_b"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_hostname_mismatch_rejected(lab_factory):
    lab = await lab_factory(include_ip=False)
    async with ClientSession() as session:
        client = UbusClient(session, lab["endpoint"], "hass", lab["credentials"]["password"], tls_context(lab["ca"]))
        with pytest.raises(ControllerError):
            await client.read("status")


async def test_native_pending_operation_polls_without_replay(client, monkeypatch):
    original = client._rpc
    writes, polls = [], []

    async def pending(sid, obj, method, args):
        if method == "set_automation":
            writes.append(args["request_id"])
            await original(sid, obj, method, args)
            return {"status": "pending", "request_id": args["request_id"]}
        if method == "operation":
            polls.append(args["request_id"])
        return await original(sid, obj, method, args)

    monkeypatch.setattr(client, "_rpc", pending)
    result = await client.mutate("set_automation", {"enabled": True}, 0)
    assert result["status"] == "completed"
    assert writes == polls and len(writes) == 1


async def test_native_rejected_operation_propagates_local_code(client, monkeypatch):
    original = client._rpc

    async def rejected(sid, obj, method, args):
        if method == "set_automation":
            return {"status": "pending"}
        if method == "operation":
            return {"status": "rejected", "error": {"code": "conflict"}}
        return await original(sid, obj, method, args)

    monkeypatch.setattr(client, "_rpc", rejected)
    with pytest.raises(RemoteError) as err:
        await client.mutate("set_automation", {"enabled": True}, 0)
    assert err.value.code == "conflict"


def test_protected_interfaces_come_from_each_controller():
    import pytest
    from custom_components.openwrt_vpn.api import ProtocolError, validate_snapshot
    from custom_components.openwrt_vpn.demo.engine import Controller
    snapshot = Controller().status()
    snapshot["sections"]["main"]["applied_vpn"] = "private_inbound"
    with pytest.raises(ProtocolError, match="Protected"):
        validate_snapshot(snapshot, protected_interfaces=["private_inbound"])
    # Another router can legitimately use the same name for an outgoing VPN.
    assert validate_snapshot(snapshot, protected_interfaces=["other_inbound"]) is snapshot
