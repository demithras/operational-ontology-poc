"""Registered mutants (monkeypatches of the Engine) and the runner that proves the state machine kills each one.

Target mutants (contract mutation_proof): (a) enable a write primitive inside Function execution,
(b) bypass an Action gate. Each is applied by monkeypatch on the live Engine modules, the machine is run on both
domains until Hypothesis finds (and shrinks) a counterexample, then the patch is removed. A clean CONTROL run
(same seed, no patch) happens before and after the mutants and must find nothing.
"""
from __future__ import annotations

import contextlib
from unittest import mock

from eoo_engine import authority, gates
from eoo_engine.registry import DISPATCH_TABLE

from .runlib import new_sink, run_machine, unique

FN_EXPECT = ("function_effect",)
GATE_EXPECT = ("gate_mismatch", "effect_log", "external_effects", "execution_class")


def _bump(v):
    return (v + 1) if isinstance(v, int) and not isinstance(v, bool) else (not v if isinstance(v, bool) else f"{v}~")


def _write_something(eng) -> None:
    """A Function implementation that holds a write primitive: mint a grant and change canonical state."""
    st = eng.state()
    for (t, k), rec in sorted(st.objects.items(), key=repr)[:60]:
        for p, v in rec["props"].items():
            op = [{"op": "update", "type": t, "key": k, "props": {p: _bump(v)}}]
            if not eng.store.plan(op)[1]:
                g = eng.minter.mint("mut")
                try:
                    eng.store.apply(g, "mut", op)
                finally:
                    eng.minter.revoke(g)
                return
    raise RuntimeError("mutant could not find a writable property")


@contextlib.contextmanager
def function_writes_effect_log():
    orig = DISPATCH_TABLE["functions"].ops["call"]

    def call(eng, spec, **kw):
        out = orig(eng, spec, **kw)
        eng.effect_log.append({"effect_id": "mutant", "execution": "mut", "action": "mutant", "operation": "write",
                               "target": "x", "payload": {}, "response": None})
        return out
    with mock.patch.dict(DISPATCH_TABLE["functions"].ops, {"call": call}):
        yield


@contextlib.contextmanager
def function_writes_store():
    orig = DISPATCH_TABLE["functions"].ops["call"]

    def call(eng, spec, **kw):
        out = orig(eng, spec, **kw)
        _write_something(eng)
        return out
    with mock.patch.dict(DISPATCH_TABLE["functions"].ops, {"call": call}):
        yield


@contextlib.contextmanager
def bypass_authority_gate():
    def allow_all(*a, **kw):
        d = authority.Decision()
        d.allowed = True
        d.allow.append("mutant")
        return d
    with mock.patch.object(authority, "evaluate", allow_all):
        yield


@contextlib.contextmanager
def bypass_precondition_gate():
    orig = gates.run_logic_gate

    def run(name, items, ctx):
        return gates.gate(name, True, {"failed": [], "errors": []}) if name == "preconditions" else orig(name, items, ctx)
    with mock.patch.object(gates, "run_logic_gate", run):
        yield


@contextlib.contextmanager
def bypass_policy_gate():
    with mock.patch.object(gates, "evaluate_policies", lambda eng, spec, ctx: ("APPROVED", gates.gate("policy", True, {}))):
        yield


@contextlib.contextmanager
def bypass_approval_requirement():
    orig = gates.evaluate_policies

    def ev(eng, spec, ctx):
        v, g = orig(eng, spec, ctx)
        return ("APPROVED", gates.gate("policy", True, g["detail"])) if v == "PENDING_APPROVAL" else (v, g)
    with mock.patch.object(gates, "evaluate_policies", ev):
        yield


REGISTRY = [
    ("MF1_function_appends_effect_log", "function_write", True, function_writes_effect_log, FN_EXPECT),
    ("MF2_function_writes_canonical_store", "function_write", True, function_writes_store, FN_EXPECT),
    ("MG1_bypass_authority_gate", "gate_bypass", True, bypass_authority_gate, GATE_EXPECT),
    ("MG2_bypass_preconditions_gate", "gate_bypass", True, bypass_precondition_gate, GATE_EXPECT),
    ("MG3_bypass_policy_gate", "gate_bypass", True, bypass_policy_gate, GATE_EXPECT),
    ("MG4_bypass_approval_requirement", "gate_bypass", True, bypass_approval_requirement, GATE_EXPECT),
]


def _run(domains, seed, n, ctx=None):
    out = {}
    for d in domains:
        sink = new_sink()
        with (ctx() if ctx else contextlib.nullcontext()):
            run_machine(d, seed, n, sink=sink)
        out[d] = sink
    return out


def control(seed: int, n: int) -> dict:
    res = _run(("manufacturing", "project"), seed, n)
    return {"examples": {d: len(s["records"]) for d, s in res.items()}, "unique": {d: unique(s) for d, s in res.items()},
            "failures": sum(len(s["failures"]) for s in res.values()),
            "clean": all(not s["failures"] for s in res.values())}


def run_mutant(row, seed: int, n: int) -> dict:
    mid, cls, target, ctx, expect = row
    found, killed_in = None, {}
    ran = {}
    for d in ("manufacturing", "project"):
        sink = new_sink()
        with ctx():
            run_machine(d, seed, n, sink=sink)
        ran[d] = len(sink["records"])
        if sink["failures"]:
            f = sink["failures"][-1]  # the last recorded failure is the shrunk counterexample's final replay
            killed_in[d] = {"kind": f["kind"], "n_steps": len(f["steps"]) - 1}
        if sink["failures"] and found is None:
            found = {"domain": d, "kind": f["kind"], "detail": f["detail"], "profile": f["profile"], "steps": f["steps"],
                     "n_steps": len(f["steps"]) - 1, "failures_recorded": len(sink["failures"]),
                     "hypothesis_note": sink.get("exception", {}).get("notes", [])[:6]}
    return {"id": mid, "class": cls, "target": target, "expected_kinds": list(expect), "killed": bool(found),
            "killed_by_expected_signal": bool(found and found["kind"] in expect), "killed_in_domains": killed_in,
            "examples_run": ran,
            "counterexample": found}


def run_all(seed: int, n_control: int, n_mutant: int) -> dict:
    before = control(seed, n_control)
    rows = [run_mutant(r, seed, n_mutant) for r in REGISTRY]
    after = control(seed, n_control)
    tgt = [r for r in rows if r["target"]]
    return {"controls": {"clean": before["clean"], "clean_after_restore": after["clean"], "before": before, "after": after},
            "mutants": rows, "summary": {"target_total": len(tgt), "target_killed": sum(r["killed_by_expected_signal"] for r in tgt),
                                         "kill_rate": (sum(r["killed_by_expected_signal"] for r in tgt) / len(tgt)) if tgt else 0.0,
                                         "classes_present": sorted({r["class"] for r in tgt})}}
