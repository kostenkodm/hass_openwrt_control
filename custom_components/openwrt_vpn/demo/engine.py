"""Deterministic controller model. All probes and Podkop changes are simulated."""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

PROTECTED = frozenset({"inbound_vpn"})
READ_METHODS = frozenset({"capabilities", "status", "sections", "vpns", "history", "operation"})
WRITE_METHODS = frozenset({"set_automation", "configure", "set_policy", "assign_vpn", "diagnose"})
CHECKS = ("resource_a", "resource_b", "resource_c")


class ModelError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


def require(condition, message, code="invalid_argument"):
    if not condition:
        raise ModelError(code, message)


def exact(args, keys):
    require(isinstance(args, dict) and set(args) == set(keys), "Unexpected or missing arguments")


def number(value, low, high, name):
    require(type(value) in (int, float) and low <= value <= high, f"Invalid {name}")
    return value


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class Controller:
    def __init__(self, path: Path | None = None, clock=time.monotonic, *, controller_id=None):
        self.path, self.clock = path, clock
        self.boot_id = str(uuid.uuid4())
        self._persisted_text = None
        self.health = {}
        self.samples = {}
        self.hold_since = {}
        self.fault = None
        if path and path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))
            require(self.data.get("schema") == 1, "Unsupported stored schema", "storage_error")
        else:
            ids = ["vpn_a", "vpn_b", "vpn_c"]
            self.data = {
                "schema": 1, "controller_id": controller_id or str(uuid.uuid4()), "revision": 0,
                "automation": False, "run_mode": "observe", "event_seq": 0,
                "settings": {"probe_interval": 60, "failure_cycles": 3,
                             "quorum": 2, "min_hold": 600},
                "vpns": {v: {"id": v, "name": v, "protocol": "simulated_awg",
                             "approved": True} for v in ids},
                "sections": {
                    sid: {"id": sid, "name": sid, "connection_type": "vpn",
                          "policy": {"mode": "manual", "vpn": vpn, "candidates": ids[:],
                                     "algorithm": "priority", "return_policy": "after_hold",
                                     "quality_margin": 5, "preferences": {}},
                          "applied_vpn": vpn, "application_state": "simulated",
                          "reason": "initial_simulated_assignment", "last_switch": None,
                          "all_unavailable": False, "proposed_vpn": vpn}
                    for sid, vpn in zip(("main", "media", "custom"), ids, strict=True)
                },
                "events": [], "operations": {}, "journal": None,
                "recovery_required": False,
            }
        journal = self.data.get("journal")
        if journal and not self.data["recovery_required"]:
            for sid, old in journal["before"].items():
                if self.data["sections"].get(sid, {}).get("applied_vpn") in (
                    old, journal["targets"][sid]
                ):
                    self.data["sections"][sid]["applied_vpn"] = old
                    self.data["sections"][sid]["application_state"] = "rolled_back"
                else:
                    self.data["recovery_required"] = True
            self._event("restart_recovery", recovery_required=self.data["recovery_required"])
            self.data["journal"] = None
        self._persist()

    def _persist(self):
        if not self.path:
            return
        serialized = json.dumps(self.data, ensure_ascii=False, allow_nan=False)
        if serialized == self._persisted_text:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            if os.name != "nt":
                os.chmod(temp, 0o600)
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, self.path)
        if os.name != "nt":
            fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        self._persisted_text = serialized

    def _event(self, kind, **context):
        self.data["event_seq"] += 1
        self.data["events"].append({
            "event_id": self.data["event_seq"], "type": kind, "time": utc_now(), **context
        })
        self.data["events"] = self.data["events"][-200:]

    def capabilities(self):
        return {
            "api_version": 1, "controller_id": self.data["controller_id"],
            "controller_kind": "simulator", "simulated": True,
            "safe_apply": False, "fail_closed_verified": False, "real_egress_verified": False,
            "simulation_control": True, "production_control": False,
            "section_endpoints": False, "protected_interfaces": sorted(PROTECTED),
            "read_methods": sorted(READ_METHODS), "write_methods": sorted(WRITE_METHODS),
        }

    def record_probe(self, vpn, successes=3, latency=50, egress=True, section_checks=None):
        require(vpn in self.data["vpns"] and vpn not in PROTECTED, "Unknown outgoing VPN")
        require(type(successes) is int and 0 <= successes <= 3, "Invalid simulated successes")
        number(latency, 0, 60000, "latency")
        require(type(egress) is bool, "Invalid simulated egress")
        previous = self.health.get(vpn, {})
        passed = successes >= self.data["settings"]["quorum"] and egress
        failures = 0 if passed else previous.get("failures", 0) + 1
        available = True if passed else previous.get("available")
        if failures >= self.data["settings"]["failure_cycles"]:
            available = False
        samples = self.samples.setdefault(vpn, deque(maxlen=10))
        samples.append(successes / 3 * 100 if egress else 0)
        self.health[vpn] = {
            "available": available, "failures": failures, "sample_at": self.clock(),
            "latency_ms": latency if successes else None,
            "success_percent": sum(samples) / len(samples),
            "stability_percent": sum(x >= 2 / 3 * 100 for x in samples) / len(samples) * 100,
            "http_test": passed, "checks": dict(zip(CHECKS, [i < successes for i in range(3)])),
            "external_ip": "198.51.100." + str(list(self.data["vpns"]).index(vpn) + 10)
                           if egress and passed else None,
            "section_checks": section_checks or {}, "simulated": True,
            "last_handshake": None, "rx_bytes": None, "tx_bytes": None,
        }
        if previous.get("available") != available and available is not None:
            self._event("vpn_recovered" if available else "vpn_failed", vpn=vpn)

    def _health(self, vpn):
        h = deepcopy(self.health.get(vpn, {}))
        fresh = bool(h) and self.clock() - h["sample_at"] <= self.data["settings"]["probe_interval"] * 2 + 5
        h.pop("sample_at", None)
        if not fresh:
            h.update(available=None, http_test=None, external_ip=None, latency_ms=None)
        h["fresh"] = fresh
        return h

    def _eligible(self, sid, vpn):
        h = self._health(vpn)
        return h.get("available") is True and h.get("section_checks", {}).get(sid, True) is True

    def _score(self, vpn, policy):
        h = self._health(vpn)
        latency = 100 / (1 + (h.get("latency_ms") or 0) / 100)
        return (h.get("success_percent", 0) * .7 + h.get("stability_percent", 0) * .2
                + latency * .1 + policy["preferences"].get(vpn, 0))

    def _choose(self, sid, section):
        policy, current = section["policy"], section["applied_vpn"]
        if policy["mode"] == "manual":
            target = policy["vpn"]
            return target if target == current or self._eligible(sid, target) else None
        usable = [v for v in policy["candidates"] if self._eligible(sid, v)]
        if not usable:
            return None
        preferred = usable[0] if policy["algorithm"] == "priority" else max(
            usable, key=lambda v: self._score(v, policy)
        )
        if current not in usable:
            # Confirmed failure overrides dwell. Unknown/stale health does not.
            if current and self._health(current).get("available") is None:
                return current
            return preferred
        hold = self.clock() - self.hold_since.setdefault(sid, self.clock())
        if preferred == current or hold < self.data["settings"]["min_hold"]:
            return current
        if policy["algorithm"] == "priority" and policy["return_policy"] == "sticky":
            return current
        if policy["algorithm"] == "quality" and (
            self._score(preferred, policy) - self._score(current, policy) < policy["quality_margin"]
        ):
            return current
        return preferred

    def _apply(self, targets, request_id):
        require(not self.data["recovery_required"], "Recovery required", "recovery_required")
        require(all(v in self.data["vpns"] and v not in PROTECTED for v in targets.values()),
                "Forbidden assignment")
        before = {sid: self.data["sections"][sid]["applied_vpn"] for sid in targets}
        self.data["journal"] = {"request_id": request_id, "before": before, "targets": targets}
        self._persist()
        fault, self.fault = self.fault, None
        try:
            if fault == "apply":
                raise ModelError("apply_error", "Simulated Podkop apply failure")
            for sid, target in targets.items():
                self.data["sections"][sid]["applied_vpn"] = target
            self._persist()
            if fault in ("verify", "rollback", "conflict"):
                raise ModelError("verify_error", "Simulated runtime verification failure")
            for sid in targets:
                section = self.data["sections"][sid]
                section.update(application_state="simulated", reason="policy_applied",
                               last_switch=utc_now())
                self.hold_since[sid] = self.clock()
                self._event("switched", section_id=sid, previous=before[sid],
                            vpn=targets[sid], request_id=request_id, simulated=True)
            outcome = "completed"
        except ModelError as err:
            self._event("apply_error", request_id=request_id, code=err.code)
            if fault in ("rollback", "conflict"):
                self.data["recovery_required"] = True
                for sid in targets:
                    self.data["sections"][sid]["application_state"] = "recovery_required"
                self._event("config_conflict" if fault == "conflict" else "rollback_error",
                            request_id=request_id)
                outcome = "recovery_required"
            else:
                for sid, old in before.items():
                    self.data["sections"][sid].update(
                        applied_vpn=old, application_state="rolled_back", reason=err.code
                    )
                self._event("rolled_back", request_id=request_id)
                outcome = "rolled_back"
        if outcome != "recovery_required":
            self.data["journal"] = None
        self._persist()
        return outcome

    def tick(self, request_id=None):
        targets = {}
        for sid, section in self.data["sections"].items():
            target = self._choose(sid, section)
            section["proposed_vpn"] = target
            unavailable = (
                section["policy"]["mode"] == "auto" and target is None
                and all(self._health(v).get("available") is False
                        for v in section["policy"]["candidates"])
            )
            if unavailable != section["all_unavailable"]:
                self._event("all_unavailable" if unavailable else "section_recovered", section_id=sid)
            section["all_unavailable"] = unavailable
            if target is None or target == section["applied_vpn"]:
                if target is not None and section["application_state"] == "pending":
                    section["application_state"] = "simulated"
                continue
            if self.data["run_mode"] != "control":
                section["application_state"] = "pending_observe"
            elif section["policy"]["mode"] == "auto" and not self.data["automation"]:
                section["application_state"] = "automation_paused"
            elif (not self.data["recovery_required"]
                  and section["application_state"] not in ("rolled_back", "recovery_required")):
                targets[sid] = target
        outcome = "completed"
        if targets:
            self.data["revision"] += 1
            outcome = self._apply(targets, request_id or "auto-" + str(uuid.uuid4()))
        self._persist()
        return outcome

    def status(self):
        return {
            "api_version": 1, "controller_id": self.data["controller_id"],
            "boot_id": self.boot_id, "revision": self.data["revision"],
            "simulated": True, "automation": self.data["automation"],
            "run_mode": self.data["run_mode"], "settings": deepcopy(self.data["settings"]),
            "recovery_required": self.data["recovery_required"],
            "podkop_status": "simulated", "sing_box_status": "simulated",
            "sections": deepcopy(self.data["sections"]),
            "vpns": {v: {**deepcopy(meta), **self._health(v)} for v, meta in self.data["vpns"].items()},
            "latest_event_id": self.data["event_seq"],
        }

    def read(self, method, args):
        if method in ("capabilities", "status", "sections", "vpns"):
            exact(args, ())
            return self.capabilities() if method == "capabilities" else (
                self.status() if method == "status" else self.status()[method]
            )
        if method == "operation":
            exact(args, ("request_id",))
            return deepcopy(self.data["operations"].get(args["request_id"], {"status": "unknown"}))
        if method == "history":
            exact(args, ("after",))
            require(type(args["after"]) is int and args["after"] >= 0, "Invalid history cursor")
            events = self.data["events"]
            return {"events": deepcopy([e for e in events if e["event_id"] > args["after"]]),
                    "cursor": self.data["event_seq"],
                    "gap": bool(events and args["after"] < events[0]["event_id"] - 1)}
        raise ModelError("method_not_found", "Unsupported method")

    def mutate(self, method, args):
        require(method in WRITE_METHODS, "Unsupported method", "method_not_found")
        keys = {
            "set_automation": {"enabled"},
            "configure": {"run_mode", "probe_interval", "failure_cycles", "quorum", "min_hold"},
            "set_policy": {"section_id", "policy"},
            "assign_vpn": {"section_id", "vpn"},
            "diagnose": set(),
        }[method] | {"request_id", "expected_revision"}
        exact(args, keys)
        request_id = args["request_id"]
        require(isinstance(request_id, str) and 8 <= len(request_id) <= 80, "Invalid request_id")
        digest = hashlib.sha256(json.dumps([method, args], sort_keys=True, allow_nan=False).encode()).hexdigest()
        if request_id in self.data["operations"]:
            previous = self.data["operations"][request_id]
            require(previous["digest"] == digest, "request_id reused with different data", "conflict")
            return deepcopy(previous)
        require(type(args["expected_revision"]) is int and
                args["expected_revision"] == self.data["revision"],
                "Configuration changed; refresh state", "conflict")
        require(not self.data["recovery_required"], "Recovery required", "recovery_required")
        if method == "set_automation":
            require(type(args["enabled"]) is bool, "Invalid enabled")
        elif method == "configure":
            require(args["run_mode"] in ("observe", "control"), "Invalid run_mode")
            number(args["probe_interval"], 1, 3600, "probe_interval")
            require(type(args["failure_cycles"]) is int, "Invalid failure_cycles")
            number(args["failure_cycles"], 1, 10, "failure_cycles")
            require(type(args["quorum"]) is int, "Invalid quorum")
            number(args["quorum"], 2, 3, "quorum")
            number(args["min_hold"], 0, 86400, "min_hold")
        elif method in ("assign_vpn", "set_policy"):
            sid = args["section_id"]
            require(isinstance(sid, str) and sid in self.data["sections"], "Unknown managed section")
            if method == "assign_vpn":
                policy = deepcopy(self.data["sections"][sid]["policy"])
                policy.update(mode="manual", vpn=args["vpn"])
            else:
                policy = args["policy"]
            exact(policy, ("mode", "vpn", "candidates", "algorithm", "return_policy",
                           "quality_margin", "preferences"))
            require(policy["mode"] in ("manual", "auto"), "Invalid mode")
            require(isinstance(policy["candidates"], list) and policy["candidates"]
                    and all(isinstance(v, str) and v in self.data["vpns"] and v not in PROTECTED
                            for v in policy["candidates"])
                    and len(policy["candidates"]) == len(set(policy["candidates"])), "Invalid candidates")
            require(isinstance(policy["vpn"], str) and policy["vpn"] in self.data["vpns"]
                    and policy["vpn"] not in PROTECTED, "Forbidden manual VPN")
            require(policy["algorithm"] in ("priority", "quality"), "Invalid algorithm")
            require(policy["return_policy"] in ("sticky", "after_hold"), "Invalid return policy")
            number(policy["quality_margin"], 0, 100, "quality margin")
            require(isinstance(policy["preferences"], dict), "Invalid preferences")
            for vpn, preference in policy["preferences"].items():
                require(vpn in policy["candidates"], "Preference for non-candidate")
                number(preference, -10, 10, "preference")
            if policy["mode"] == "manual" and policy["vpn"] != self.data["sections"][sid]["applied_vpn"]:
                require(self._eligible(sid, policy["vpn"]), "VPN not confirmed available", "unavailable")
        self.data["revision"] += 1
        if method == "set_automation":
            self.data["automation"] = args["enabled"]
        elif method == "configure":
            self.data["run_mode"] = args["run_mode"]
            self.data["settings"].update({k: args[k] for k in self.data["settings"]})
        elif method in ("set_policy", "assign_vpn"):
            self.data["sections"][sid]["policy"] = deepcopy(policy)
            self.data["sections"][sid]["application_state"] = "pending"
            self._event("policy_changed", section_id=sid, mode=policy["mode"], request_id=request_id)
        self._persist()
        outcome = self.tick(request_id)
        result = {"status": outcome, "request_id": request_id, "revision": self.data["revision"],
                  "digest": digest, "simulated": True}
        self.data["operations"][request_id] = result
        # Prototype retention is bounded; requests older than this window must not be retried.
        while len(self.data["operations"]) > 256:
            del self.data["operations"][next(iter(self.data["operations"]))]
        self._persist()
        return deepcopy(result)
