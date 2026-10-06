"""A8 crash / restart rules (PROT-H23-A8 R5, R9). Sequential driver; every scenario is oracle-judged per call.

  crash_before  arm_crash(before_commit) + a request that the oracle says commits -> (crash) -> request on the crashed
                deployment (must be UNAVAILABLE, zero effects) -> restart -> replay SAME id -> request with a NEW id
  crash_after   same with after_commit: the crashed call's world diff must be exactly the request's effects; the
                same-id replay must add nothing (a second effect = crash_duplicate_effect)
  crash_idle    commit, crash() between requests, UNAVAILABLE probe, restart, replay same id, new request continues

The armed request is always one the oracle predicts will commit, so the crash point is reached. `crash_triggered`
(did the variant report the crash) is the one use of CallResult in classification, because a crash leaves no world
trace; an armed crash that never triggers is cleared with crash()+restart() and the call is judged as an ordinary one.
Scenarios need a quiet approval ledger (the protocol does not say whether pre-approvals survive a crash).
"""
from __future__ import annotations

import copy

from r3_oracle import ops_model

from .goodargs import pick_args

RULES = ("crash_before", "crash_after", "crash_idle")
POINT = {"crash_before": "before_commit", "crash_after": "after_commit"}
# every label the evaluator requires to be exercised (":armed" labels must also have triggered)
REQUIRED = ("crash_before:armed", "crash_before:unavailable", "crash_before:replay-same", "crash_before:replay-new",
            "crash_after:armed", "crash_after:unavailable", "crash_after:replay-same", "crash_after:replay-new",
            "crash_idle:pre", "crash_idle:unavailable", "crash_idle:replay-same", "crash_idle:continue")


def gen_step(env, ch, attacker: str, rule: str) -> dict | None:
    """None -> caller falls back to a legit step (no committing request found, or approvals are outstanding)."""
    if any(v > 0 for v in env.approvals.values()) or env.crashed:
        return None
    ops = {o["name"]: o for o in env.ops["operations"]}
    snap = env.snapshot()
    mine = env.authorized_ops(attacker)
    for _ in range(6 if mine else 0):
        name = ch.choice(mine)
        args = pick_args(env, ops[name], ch, attacker, "commit")
        out = ops_model.evaluate(env.ops, env.auth, attacker, None, name, args, snap, env.clock.now(),
                                 frozenset(env.committed), None)
        if out.commits:
            via = "call_tool" if name in env.tools(attacker) else "direct"
            return {"rule": rule, "attacker": attacker, "via": via, "op": name, "args": args, "obo": None,
                    "tok": {"kind": "valid", "sub": attacker}, "extra": {}}
    return None


def _call(env, step, label, *, rid, args=None, clean=False, point=None):
    a = step["attacker"]
    return env.call(rule=f"{step['rule']}:{label}", via=step["via"], token=env.token(a), subject=a,
                    operation=step["op"], args=copy.deepcopy(step["args"] if args is None else args),
                    request_id=rid, tags=(), clean=clean, crash_point=point)


def _unsupported(env, step, exc) -> list[dict]:
    return [{"rule": f"{step['rule']}:unsupported", "via": "arm_crash", "subject": step["attacker"],
             "operation": step["op"], "args": {}, "classes": ["crash_unsupported"], "status": "EXCEPTION",
             "error": f"{type(exc).__name__}: {exc}", "tags": [], "clean": False, "legit_expected": False,
             "legit_ok": None, "backstop_tested": False, "backstop_pass": None, "measured": [], "unexpected": [],
             "missing": [], "bad_writer": [], "oracle": "n/a", "oracle_detail": "", "oracle_error": None,
             "in_tools": None, "latency_ms": 0.0, "on_behalf_of": None, "request_id": None, "expected_n": 0,
             "measured_n": 0, "crash_point": None, "crash_triggered": False}]


def exe(env, step: dict) -> list[dict]:
    rule = step["rule"]
    rid = lambda t: f"rq-{env.tag}-{env.n}-{t}"  # noqa: E731
    first = rid("k1")
    if rule == "crash_idle":
        recs = [_call(env, step, "pre", rid=first, clean=True)]
        try:
            env.crash_now()
        except Exception as exc:  # noqa: BLE001
            return recs + _unsupported(env, step, exc)
        recs.append(_call(env, step, "unavailable", rid=rid("k2")))
        env.restart()
        recs.append(_call(env, step, "replay-same", rid=first))
        recs.append(_call(env, step, "continue", rid=rid("k3"), clean=True))
        return recs
    point = POINT[rule]
    try:
        env.dep.arm_crash(point)
    except Exception as exc:  # noqa: BLE001
        return _unsupported(env, step, exc)
    recs = [_call(env, step, "armed", rid=first, point=point)]
    if not env.crashed:  # armed request refused or crash not reported: clear the pending arm, judge as ordinary
        env.disarm()
        return recs
    recs.append(_call(env, step, "unavailable", rid=rid("k2")))
    env.restart()
    recs.append(_call(env, step, "replay-same", rid=first))
    recs.append(_call(env, step, "replay-new", rid=rid("k3")))
    return recs
