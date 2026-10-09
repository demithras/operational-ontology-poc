"""Oracle-backed case construction (ORACLE-AND-HARNESS-G4 s2): reachability and validity are built in (G3-E28/E30/E32 lessons).
The world is the frozen seed (reachable by definition); every request is evaluated by the ORACLE (r3_oracle.extoracle.decide) on
the predicted snapshot and re-drawn until it has the intended class (80% oracle-OK, 20% approval/deny probes); the twin shares the
step list (equal schedules, G3-E32b). Never raises: an exhausted draw is returned as None and counted (`generator_redraw_exhausted`)."""
from __future__ import annotations

import random

from r3_harness.h23.chooser import RandChooser
from r3_harness.h23.goodargs import random_args
from r3_harness.h26 import sim
from r3_oracle import approvals, extoracle, ops_model

from . import specs

MAX_TRIES = 80
STR_POOL = {"visibility": ["internal", "public"], "reviewer": ["rev-a", "rev-b", "rev-c"]}


def _principals(auth: dict) -> list[str]:
    return [p["id"] for p in auth["principals"]]


def seed_snapshot(ops: dict) -> dict:
    return sim.apply_changes(sim.empty(), [c for b in sim.seed_batches(ops) for c in b])


def _args(op: dict, snap: dict, ch, idx: int) -> dict:
    if op["name"] == specs.GEN_OP:
        return {"key": f"g{idx}-{ch.randint(0, 999)}"}
    a = random_args(op, snap, ch)
    for i in op["inputs"]:                                     # H28 string pools: values the project overlay rules distinguish
        if i["name"] in STR_POOL and (i["required"] or i["name"] in a):
            a[i["name"]] = ch.choice(STR_POOL[i["name"]])
    return a


def _draw(ops, auth, snap, opname, want, ch, idx, committed=frozenset(), exclude_subject=None):
    """(subject, args, decision, approver|None) whose oracle verdict class is `want`: commit | approval | commit_approved."""
    op = ops_model.op_of(ops, opname)
    if op is None:
        return None
    for _ in range(MAX_TRIES):
        sub = ch.choice(_principals(auth))
        args = _args(op, snap, ch, idx)
        d = extoracle.decide(ops, auth, sub, None, opname, args, snap, 0, committed, None, approved=False)
        if want == "commit" and d.kind == "OK" and d.outcome.effects and not d.outcome.used_approval:
            return sub, args, d, None
        if want in ("approval", "commit_approved") and d.outcome is not None and d.outcome.kind == ops_model.NEEDS_APPROVAL:
            if want == "approval":
                return sub, args, d, None
            for ap in _principals(auth):
                if approvals.validate(ops, auth, ap, sub, opname, args)[0]:
                    d2 = extoracle.decide(ops, auth, sub, None, opname, args, snap, 0, committed, None, approved=True)
                    if d2.kind == "OK" and d2.outcome.used_approval:
                        return sub, args, d2, ap
    return None


def _approval_op(ops: dict) -> str | None:
    return next((o["name"] for o in ops["operations"] if o.get("approval") and any(e.get("kind") == "external" for e in o["effects"])),
                None)


def build_case(params: dict, run_seed: int, stats: dict) -> dict | None:
    """Return the full case dict (JSON-able) or None when the draw budget is exhausted (counted)."""
    idx, domain, system = params["idx"], params["domain"], params["system"]
    ops, auth, systems = specs.load(domain)
    if system == "GEN-NULL":
        ops, auth = specs.with_gen_null(ops, auth)
    snap = seed_snapshot(ops)
    ch = RandChooser(random.Random(f"{run_seed}:{params['kind']}:{idx}"))
    want = "commit"
    if params.get("approved_flow"):
        want = "commit_approved"
    elif params.get("denied"):
        want = "approval"
    pick = _draw(ops, auth, snap, params["op"], want, ch, idx)
    if pick is None and want != "commit":                      # no such request reachable for this op: plain OK request instead
        stats["redraw_fallback"] = stats.get("redraw_fallback", 0) + 1
        want, pick = "commit", _draw(ops, auth, snap, params["op"], "commit", ch, idx)
    if pick is None:
        stats["generator_redraw_exhausted"] = stats.get("generator_redraw_exhausted", 0) + 1
        return None
    sub, args, dec, approver = pick
    reqs = [{"i": 0, "rid": f"h28-{params['kind'][0]}{idx:06d}-0", "subject": sub, "obo": None, "operation": params["op"],
             "args": args, "via": params["via"], "approver": approver, "expect": want}]
    probe = [q for q in params["prims"] if q in ("G1", "G2")]
    if probe:                                                  # Q12: 2-request cases for G1/G2 (artefact consumption follow-up)
        aop = _approval_op(ops)
        p2 = _draw(ops, auth, snap, aop, "approval", ch, idx) if aop else None
        if p2 is not None:
            reqs.append({"i": 1, "rid": f"h28-{params['kind'][0]}{idx:06d}-1", "subject": p2[0], "obo": None, "operation": aop,
                         "args": p2[1], "via": "direct", "approver": None, "expect": "approval"})
    steps = _steps(params, reqs)
    case = {**params, "id": f"{params['kind']}-{idx:06d}", "requests": reqs, "steps": steps, "window": systems["window"],
            "gen_null_ops": system == "GEN-NULL"}
    return case


def _steps(p: dict, reqs: list) -> list[dict]:
    adv = list(p["adv"])
    nxt = lambda: adv.pop() if adv else 0  # noqa: E731
    s: list[dict] = []
    fault = p.get("fault")
    for r in reqs:
        if r["approver"]:
            s.append({"op": "approve", "i": r["i"]})
        if p.get("crash") and r["i"] == 0:
            s.append({"op": "arm_crash", "point": p["crash"]})
        s.append({"op": "request", "i": r["i"]})
        if p.get("crash") and r["i"] == 0:
            s += [{"op": "restart"}]
        s.append({"op": "dispatch"})
    for _ in range(p["extra_dispatch"]):
        s += [{"op": "advance", "n": nxt()}, {"op": "dispatch"}]
    if p.get("replay"):
        s += [{"op": "request", "i": 0, "replay": True}, {"op": "dispatch"}]
    for _ in range(p["mid"]):
        s += [{"op": "advance", "n": nxt()}, {"op": "reconcile", "fault": fault}]
    if fault and p["mid"] == 0:
        s.append({"op": "reconcile", "fault": fault})
    s += [{"op": "dispatch"}, {"op": "final"}]
    return s
