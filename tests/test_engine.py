from copy import deepcopy
import uuid

import pytest

from simulator.engine import Controller, ModelError


def command(c, method, **values):
    return c.mutate(method, {**values, "request_id": str(uuid.uuid4()),
                            "expected_revision": c.data["revision"]})


def healthy(c):
    for vpn in c.data["vpns"]:
        c.record_probe(vpn)


def policy(c, sid="main", **values):
    result = deepcopy(c.data["sections"][sid]["policy"])
    result.update(values)
    return result


def control(c):
    return command(c, "configure", run_mode="control", **c.data["settings"])


def auto(c, sid="main", **values):
    command(c, "set_policy", section_id=sid, policy=policy(c, sid, mode="auto", **values))


def fail(c, vpn, cycles=3):
    for _ in range(cycles):
        c.record_probe(vpn, successes=0, egress=False)
        c.tick()


def test_observe_and_defaults():
    c = Controller()
    healthy(c)
    auto(c, candidates=["vpn_b", "vpn_a"])
    command(c, "set_automation", enabled=True)
    assert c.data["sections"]["main"]["applied_vpn"] == "vpn_a"
    assert c.data["sections"]["main"]["proposed_vpn"] == "vpn_a"  # minimum hold
    assert c.data["run_mode"] == "observe"
    assert c.capabilities()["safe_apply"] is False
    assert c.capabilities()["real_egress_verified"] is False


def test_manual_persists_and_is_not_changed_by_automation(tmp_path):
    c = Controller(tmp_path / "state.json")
    healthy(c)
    control(c)
    command(c, "assign_vpn", section_id="main", vpn="vpn_b")
    command(c, "set_automation", enabled=True)
    fail(c, "vpn_b")
    assert c.data["sections"]["main"]["applied_vpn"] == "vpn_b"
    restarted = Controller(c.path)
    assert restarted.data["sections"]["main"]["policy"]["vpn"] == "vpn_b"
    assert restarted.status()["vpns"]["vpn_b"]["available"] is None


def test_three_failed_cycles_switch_only_auto_section():
    c = Controller()
    healthy(c)
    control(c)
    auto(c)
    command(c, "set_automation", enabled=True)
    fail(c, "vpn_a", 2)
    assert c.data["sections"]["main"]["applied_vpn"] == "vpn_a"
    fail(c, "vpn_a", 1)
    assert c.data["sections"]["main"]["applied_vpn"] == "vpn_b"
    assert c.data["sections"]["custom"]["applied_vpn"] == "vpn_c"
    assert c.data["sections"]["media"]["policy"]["mode"] == "manual"


def test_all_unavailable_no_new_assignment_and_no_event_spam():
    c = Controller()
    healthy(c)
    control(c)
    auto(c)
    command(c, "set_automation", enabled=True)
    for _ in range(3):
        for vpn in c.data["vpns"]:
            c.record_probe(vpn, successes=0, egress=False)
        c.tick()
    assert c.data["sections"]["main"]["applied_vpn"] == "vpn_a"
    for _ in range(5):
        c.tick()
    assert len([e for e in c.data["events"] if e["type"] == "all_unavailable"]) == 1
    c.record_probe("vpn_b")
    c.tick()
    assert c.data["sections"]["main"]["applied_vpn"] == "vpn_b"


def test_two_resources_suffice_but_no_egress_is_failure():
    c = Controller()
    c.record_probe("vpn_a", successes=2)
    assert c.status()["vpns"]["vpn_a"]["available"] is True
    fail(c, "vpn_a")
    assert c.status()["vpns"]["vpn_a"]["available"] is False


@pytest.mark.parametrize("fault", ["apply", "verify"])
def test_apply_failure_rolls_back(fault):
    c = Controller()
    healthy(c)
    control(c)
    c.fault = fault
    result = command(c, "assign_vpn", section_id="main", vpn="vpn_b")
    assert result["status"] == "rolled_back"
    assert c.data["sections"]["main"]["applied_vpn"] == "vpn_a"
    assert c.data["sections"]["main"]["policy"]["vpn"] == "vpn_b"
    assert c.data["journal"] is None


@pytest.mark.parametrize("fault", ["rollback", "conflict"])
def test_unrecoverable_error_blocks_further_writes(fault):
    c = Controller()
    healthy(c)
    control(c)
    c.fault = fault
    assert command(c, "assign_vpn", section_id="main", vpn="vpn_b")["status"] == "recovery_required"
    with pytest.raises(ModelError, match="Recovery required"):
        command(c, "set_automation", enabled=True)
    assert c.data["journal"] is not None


def test_revision_conflict_and_request_deduplication():
    c = Controller()
    args = {"enabled": True, "request_id": str(uuid.uuid4()), "expected_revision": 0}
    result = c.mutate("set_automation", args)
    assert c.mutate("set_automation", args) == result
    assert c.data["revision"] == 1
    with pytest.raises(ModelError) as error:
        c.mutate("set_automation", {**args, "enabled": False})
    assert error.value.code == "conflict"
    with pytest.raises(ModelError):
        c.mutate("set_automation", {**args, "request_id": str(uuid.uuid4())})


@pytest.mark.parametrize("vpn", ["inbound_vpn", "wan", "$(reboot)", "vpn_a; reboot", "unknown"])
def test_forbidden_assignment(vpn):
    c = Controller()
    healthy(c)
    before = deepcopy(c.data)
    with pytest.raises(ModelError):
        command(c, "assign_vpn", section_id="main", vpn=vpn)
    assert c.data == before


def test_unknown_section_and_extra_keys_rejected():
    c = Controller()
    with pytest.raises(ModelError):
        command(c, "assign_vpn", section_id="proxy", vpn="vpn_a")
    with pytest.raises(ModelError):
        command(c, "diagnose", command="reboot")
    assert c.data["revision"] == 0


def test_quality_hysteresis_dwell_and_preferences():
    now = [0]
    c = Controller(clock=lambda: now[0])
    c.record_probe("vpn_a", latency=1000)
    c.record_probe("vpn_b", latency=10)
    c.record_probe("vpn_c", latency=100)
    control(c)
    auto(c, algorithm="quality")
    command(c, "set_automation", enabled=True)
    assert c.data["sections"]["main"]["applied_vpn"] == "vpn_a"
    now[0] = 601
    c.record_probe("vpn_a", latency=1000)
    c.record_probe("vpn_b", latency=10)
    c.record_probe("vpn_c", latency=100)
    c.tick()
    assert c.data["sections"]["main"]["applied_vpn"] == "vpn_b"


def test_stale_probe_is_unknown_and_does_not_claim_egress():
    now = [0]
    c = Controller(clock=lambda: now[0])
    healthy(c)
    now[0] = 126
    h = c.status()["vpns"]["vpn_a"]
    assert h["available"] is None
    assert h["external_ip"] is None
    assert h["fresh"] is False


def test_restart_recovers_incomplete_simulated_apply(tmp_path):
    c = Controller(tmp_path / "state.json")
    c.data["journal"] = {"request_id": "crash-test", "before": {"main": "vpn_a"},
                         "targets": {"main": "vpn_b"}}
    c.data["sections"]["main"]["applied_vpn"] = "vpn_b"
    c._persist()
    recovered = Controller(c.path)
    assert recovered.data["sections"]["main"]["applied_vpn"] == "vpn_a"
    assert recovered.data["journal"] is None


def test_history_retention_reports_gap():
    c = Controller()
    for i in range(205):
        c._event("test_event", sequence=i)
    history = c.read("history", {"after": 0})
    assert history["gap"] is True
    assert len(history["events"]) == 200


def test_multiple_sections_are_grouped_in_one_apply():
    c = Controller()
    healthy(c)
    control(c)
    auto(c, "main")
    auto(c, "custom", candidates=["vpn_a", "vpn_b", "vpn_c"])
    command(c, "set_automation", enabled=True)
    for _ in range(3):
        c.record_probe("vpn_a", successes=0, egress=False)
        c.record_probe("vpn_c", successes=0, egress=False)
    c.tick()
    events = [e for e in c.data["events"] if e["type"] == "switched"]
    assert {e["section_id"] for e in events} == {"main", "custom"}
    assert len({e["request_id"] for e in events}) == 1


def test_discovery_model_has_no_three_vpn_limit():
    c = Controller()
    for i in range(5):
        ident = f"extra_{i}"
        c.data["vpns"][ident] = {"id": ident, "approved": True, "protocol": "simulated"}
        c.record_probe(ident)
    assert len(c.status()["vpns"]) == 8
    assert "inbound_vpn" not in c.status()["vpns"]


def test_rollback_requires_new_policy_command_before_retry():
    c = Controller()
    healthy(c)
    control(c)
    c.fault = "verify"
    command(c, "assign_vpn", section_id="main", vpn="vpn_b")
    for _ in range(5):
        c.tick()
    assert c.data["sections"]["main"]["applied_vpn"] == "vpn_a"
    assert len([e for e in c.data["events"] if e["type"] == "apply_error"]) == 1
    command(c, "assign_vpn", section_id="main", vpn="vpn_b")
    assert c.data["sections"]["main"]["applied_vpn"] == "vpn_b"


def test_unknown_health_does_not_raise_all_unavailable():
    c = Controller()
    auto(c)
    assert c.data["sections"]["main"]["all_unavailable"] is False
    assert not any(e["type"] == "all_unavailable" for e in c.data["events"])


def test_idle_ticks_do_not_rewrite_persistent_state(tmp_path):
    c = Controller(tmp_path / "state.json")
    healthy(c)
    c.tick()
    modified = c.path.stat().st_mtime_ns
    for _ in range(5):
        c.tick()
    assert c.path.stat().st_mtime_ns == modified


def test_existing_demo_upgrades_restart_metadata_without_resetting_policies(tmp_path):
    from copy import deepcopy
    from custom_components.openwrt_vpn.demo.engine import Controller
    path = tmp_path / "controller.json"
    old = Controller(path)
    for meta in old.data["vpns"].values():
        meta.pop("restart_allowed", None)
    old.data["vpns"]["vpn_b"]["restart_allowed"] = False
    policies = deepcopy(old.data["sections"])
    old._persist()
    upgraded = Controller(path)
    assert upgraded.data["sections"] == policies
    assert upgraded.data["revision"] == old.data["revision"]
    assert upgraded.data["vpns"]["vpn_a"]["restart_allowed"] is True
    assert upgraded.data["vpns"]["vpn_b"]["restart_allowed"] is False
