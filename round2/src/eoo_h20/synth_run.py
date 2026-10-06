"""Execute one synthetic definition end to end on the UNCHANGED Engine and compare it with the independent oracle."""
from __future__ import annotations

import hashlib
import itertools
import json

from eoo_engine import AdapterRegistry, CapabilityError, Engine, Journal, Principal
from eoo_exp.util import ROOT, canon, load_oracle, sha_text

from . import synth

O = load_oracle("h20", "synth_oracle")
L = load_oracle("h20", "lifecycle")
_PROFILE = {"actor": (None, True), "roleonly": (None, False), "relonly": (set(), True),
            "outsider": (set(), False)}


def _clock():
    c = itertools.count()
    return lambda: f"t{next(c):08d}"


def structure_sha(d: dict) -> str:
    """Hash of the definition with every generated id/number normalised away: the *shape* of the case."""
    a, s = d["action"], d["scenario"]
    shape = {"fn": d["fn"]["kind"], "a": {k: v for k, v in a.items() if k not in ("policy_t", "cap")},
             "s": {k: v for k, v in s.items() if k != "n"}, "n_sign": (s["n"] > 0, s["n"] > a["policy_t"], s["n"] > a["cap"])}
    return sha_text(canon(shape))


def definition_sha(d: dict) -> str:
    return sha_text(canon(d))


def run(d: dict, trace=None) -> dict:
    """Returns one result row; ``mismatches`` is empty when the Engine agrees with the oracle on every checked fact."""
    n, a, s = synth.ids(d), d["action"], d["scenario"]
    pkg = synth.package(d)
    sysd = synth.SynSys(s["adapter"], n["obs"])
    eng = Engine(pkg, synth.bindings(d), AdapterRegistry({("external_call", "SynSys"): sysd}), clock=_clock())
    roles, rel = _PROFILE.get(s["principal"], (set(), False))
    roles = {n["actor"]} if roles is None else roles
    relations = {(n["T"], "t0", "owner")} if rel else set()
    if s["principal"] != "ghost":
        eng.register_principal(Principal("p1", roles, relations))
    eng.register_principal(Principal("ap1", {n["approver"]}))
    eng.register_principal(Principal("second", {n["actor"]}))
    eng.seed([{"op": "create", "type": n["T"], "key": "t0", "props": {"key": "t0", "n": 0}},
              {"op": "create", "type": n["S"], "key": "s0", "props": {"key": "s0"}}])
    mism, exp = [], O.expected(d)
    st0, fp0 = eng.state().state_hash(), eng.fingerprint()
    # Function path: value from the oracle, no effect of any kind
    fv = eng.call_function(n["fn"], {"box": "t0"})
    if fv != O.function_value(d["fn"], 0):
        mism.append(f"function value {fv!r}")
    if eng.state().state_hash() != st0 or len(eng.effect_log) or sysd.calls:
        mism.append("function call changed the world")
    # governed Action path
    if a["effect"] == "create":
        inputs = {"key": "t0" if s["ref"] == "dup" else "t1", "n": s["n"]}
    elif a["effect"] == "link":
        inputs = {"box": "t0" if s["ref"] == "good" else "nope", "shelf": "s0", "n": s["n"]}
    else:
        inputs = {"box": "t0" if s["ref"] == "good" else "nope", "n": s["n"]}
    key = "k1" if s["key"] == "present" else None
    rec = eng.propose(n["act"], inputs, "p1", idempotency_key=key)
    pending_exc = None
    if rec["state"] == "PENDING_APPROVAL":
        who = {"approve": "ap1", "reject": "ap1", "self": "p1", "unauthorized": "second"}[s["approval"]]
        try:
            rec = (eng.reject if s["approval"] == "reject" else eng.approve)(rec["exec"], who)
        except CapabilityError as exc:
            pending_exc = type(exc).__name__
            rec = eng.executions[rec["exec"]]
    failed = [g["gate"] for g in rec["gates"] if not g["passed"]]
    if rec["state"] != exp["state"]:
        mism.append(f"state {rec['state']} != {exp['state']}")
    if (failed[0] if failed else None) != exp["gate"]:
        mism.append(f"failed gate {failed} != {exp['gate']}")
    if exp["state"] == "PENDING_APPROVAL" and not pending_exc:
        mism.append("a refused approval did not raise")
    committed = "EFFECTS_COMMITTED" in rec["history"]
    if committed != exp["committed"] or len(eng.effect_log) != (O.n_effects(a["effect"]) if exp["committed"] else 0):
        mism.append(f"effect log {len(eng.effect_log)} committed={committed} expected={exp['committed']}")
    if (eng.state().state_hash() != st0) != exp["store_changes"]:
        mism.append(f"store changed={eng.state().state_hash() != st0} expected={exp['store_changes']}")
    if sysd.calls != exp["external_calls"]:
        mism.append(f"external calls {sysd.calls} != {exp['external_calls']}")
    if bool(rec["soft_flags"]) != exp["soft"] and exp["state"] not in ("DENIED", "PENDING_APPROVAL"):
        mism.append(f"soft flags {rec['soft_flags']} != {exp['soft']}")
    hp = L.history_problem(list(rec["history"]))
    if hp:
        mism.append("lifecycle: " + hp)
    prov = [e for e in eng.provenance.entries() if e.get("exec") == rec["exec"] and "state" in e]
    pfields = list(prov[-1]) if prov else []
    if not prov or any(f not in pfields for f in L.PROVENANCE_REQUIRED_FIELDS) or prov[-1]["state"] != rec["state"]:
        mism.append("provenance record missing or not final")
    retry_ok = True
    if s["retry"] and key is not None and rec["state"] != "PENDING_APPROVAL":
        n_log, calls = len(eng.effect_log), sysd.calls
        again = eng.propose(n["act"], inputs, "p1", idempotency_key=key)
        retry_ok = again["exec"] == rec["exec"] and len(eng.effect_log) == n_log and sysd.calls == calls
        if not retry_ok:
            mism.append("retry with the same key was not idempotent")
    j2 = Journal()
    j2.records = [dict(r) for r in eng.journal]
    replay_ok = Engine(pkg, synth.bindings(d), eng.adapters, journal=j2, clock=_clock()).fingerprint() == eng.fingerprint()
    if not replay_ok:
        mism.append("rebuilding the Engine from its journal changed the state")
    return {"sha": definition_sha(d), "structure_sha": structure_sha(d), "effect": a["effect"], "policy": a["policy"],
            "principal": s["principal"], "expected_state": exp["state"], "observed_state": rec["state"],
            "history": list(rec["history"]), "provenance_fields": pfields, "retry_ok": retry_ok, "replay_ok": replay_ok,
            "kinds": sorted(k for k, v in pkg.items() if isinstance(v, list) and v), "mismatches": mism}
