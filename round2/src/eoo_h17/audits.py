"""Function-only trace audit and the enumerated negative-Action results (both domains)."""
from __future__ import annotations

import json

import hypothesis.strategies as st
from hypothesis import HealthCheck, Phase, given, seed as hseed, settings

from eoo_engine import EngineError
from eoo_exp.util import sha_text

from . import calls
from .drivers import MFG_LATER, new_driver
from .scenarios import ALL, PROFILES, for_profile

GATE = {"fresh": "stale"}


# ---- Function-only traces ---------------------------------------------------------------------------
def run_function_only(domain: str, profile: str, steps: list) -> dict:
    """steps: [("read"|"function", pick, variant, via_tool)]. Returns one audit row (before/after of EffectLog + store)."""
    drv = new_driver(domain, profile)
    before = drv.marker()
    errors = 0
    for kind, pick, variant, via_tool in steps:
        try:
            if kind == "read":
                types = calls.read_targets(drv)
                t = types[pick % len(types)]
                keys = drv.ref_keys(t)
                if keys:
                    drv.engine.get(t, keys[pick % len(keys)])
                drv.engine.dispatch("object_types", "list", t)
            else:
                fid, args, _label = calls.make_call(drv, pick, variant)
                eng = drv.engine
                (eng.tool("planner-1" if domain == "manufacturing" else "researcher-1").call_function(fid, args)
                 if via_tool else eng.call_function(fid, args))
        except EngineError:
            errors += 1
    after = drv.marker()
    return {"domain": domain, "profile": profile, "sha": sha_text(json.dumps([domain, profile, steps], sort_keys=True)),
            "n_steps": len(steps), "function_calls": sum(1 for s in steps if s[0] == "function"), "refused_calls": errors,
            "effect_log_before": before["effect_log"], "effect_log_after": after["effect_log"],
            "effect_digest_equal": before["effect_digest"] == after["effect_digest"],
            "store_equal": before["store"] == after["store"], "external_before": before["external"],
            "external_after": after["external"], "external_equal": before["external_fp"] == after["external_fp"],
            "identical": before == after}


def function_only_rows(domain: str, seed_: int, n: int) -> list:
    rows = []
    step = st.tuples(st.sampled_from(["read", "function", "function"]), st.integers(0, 999), st.integers(0, 5), st.booleans())

    @given(profile=st.sampled_from(PROFILES[domain]), steps=st.lists(step, min_size=1, max_size=8))
    @settings(max_examples=n, deadline=None, database=None, suppress_health_check=list(HealthCheck),
              phases=(Phase.generate,), derandomize=False)
    def body(profile, steps):
        rows.append(run_function_only(domain, profile, steps))
    hseed(seed_)(body)()
    return rows


# ---- Negative actions: every denied / unauthorized / stale / precondition-failed / unapproved action ---------------
def _row(drv, case, scn, rec, before, via, extra=None) -> dict:
    after = drv.marker()
    failed = [g["gate"] for g in rec["gates"] if not g["passed"]] if rec else []
    return {"case": case, "domain": drv.DOMAIN, "profile": drv.profile, "scenario": scn.id, "kind": scn.kind, "via": via,
            "adapter_mode": drv.adapter.mode, "final_state": rec["state"] if rec else None, "failed_gates": failed,
            "expected_gate": GATE.get(_expected(scn), _expected(scn)), "effect_log_delta": after["effect_log"] - before["effect_log"],
            "external_delta": after["external"] - before["external"], "store_equal": after["store"] == before["store"],
            "zero_effects": after == before or (after["store"] == before["store"] and after["effect_log"] == before["effect_log"]
                                                and after["external"] == before["external"]), **(extra or {})}


def _expected(scn):
    for g in ("identity", "request", "inputs", "fresh", "authority", "preconditions"):
        if not scn.tokens.get(g, True):
            return g
    return "policy" if scn.tokens["policy"] == "deny" else None


def negative_rows(domain: str) -> list:
    rows = []
    for profile in PROFILES[domain]:
        for scn in for_profile(domain, profile, "unauthorized", "invalid"):
            for via in ("engine", "tool"):
                for mode in ("ok", "timeout"):
                    drv = new_driver(domain, profile)
                    drv.set_mode(mode)
                    if scn.clock:
                        drv.clock["now"] = MFG_LATER
                    before = drv.marker()
                    key = "n1" if scn.key else None
                    if via == "tool" and scn.expected_versions is None:
                        rec = drv.engine.tool(scn.principal).propose_action(scn.action, scn.inputs, idempotency_key=key)
                    else:
                        rec = drv.engine.propose(scn.action, scn.inputs, scn.principal, idempotency_key=key,
                                                 expected_versions=scn.expected_versions)
                    rows.append(_row(drv, f"denied:{scn.kind}", scn, rec, before, via))
        for scn in for_profile(domain, profile, "ok"):  # idempotency-key reuse with a different intent
            if scn.alt_inputs:
                drv = new_driver(domain, profile)
                drv.engine.propose(scn.action, scn.inputs, scn.principal, idempotency_key="d1")
                before = drv.marker()
                rec = drv.engine.propose(scn.action, scn.alt_inputs, scn.principal, idempotency_key="d1")
                rows.append(_row(drv, "denied:key_reuse_different_intent", scn, rec, before, "engine",
                                 {"expected_gate": "idempotency"}))
        for scn in for_profile(domain, profile, "approval"):  # rejected / wrongly approved / executed-while-unapproved
            for who, mode in [(a, "approve_bad") for a in scn.approvers_bad] + [(a, "reject_ok") for a in scn.approvers_ok]:
                drv = new_driver(domain, profile)
                rec = drv.engine.propose(scn.action, scn.inputs, scn.principal, idempotency_key="a1")
                before = drv.marker()
                try:
                    (drv.engine.reject if mode == "reject_ok" else drv.engine.approve)(rec["exec"], who)
                    outcome = "returned"
                except EngineError as e:
                    outcome = type(e).__name__
                rows.append(_row(drv, f"unapproved:{mode}", scn, drv.engine.executions[rec["exec"]], before, "engine",
                                 {"approver": who, "outcome": outcome, "expected_gate": "approval"}))
            drv = new_driver(domain, profile)
            rec = drv.engine.propose(scn.action, scn.inputs, scn.principal, idempotency_key="a1")
            before = drv.marker()
            try:
                drv.engine.dispatch("actions", "execute", scn.action, execution=rec["exec"])
                outcome = "returned"
            except EngineError as e:
                outcome = type(e).__name__
            rows.append(_row(drv, "unapproved:execute_while_pending", scn, drv.engine.executions[rec["exec"]], before,
                             "engine", {"outcome": outcome, "expected_gate": None}))
    return rows
