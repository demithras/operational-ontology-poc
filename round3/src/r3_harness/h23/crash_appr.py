"""R-6 (approvals are durable and single-use across crashes). Scenario per point (before_commit / after_commit):

  approve (valid approver, ledger entry) -> arm_crash(point) -> commit (crash) -> UNAVAILABLE probe -> restart ->
  replay-same (same id) -> replay-new (NEW id, same request)

Oracle (env.call, unchanged): before_commit leaves the approval UNCONSUMED, so replay-same commits (exactly once) and
replay-new then finds it consumed (zero effects); after_commit consumed it exactly once, so replay-same adds nothing
(id ledger) and replay-new gets zero effects. A lost approval shows as `crash_approval_lost` (a commit the oracle
expected is missing), a double-consumed one as `crash_approval_reuse` (an effect the oracle forbids).
"""
from __future__ import annotations

import copy

from . import approval_rules

RULES = ("crash_appr_before", "crash_appr_after")
POINT = {"crash_appr_before": "before_commit", "crash_appr_after": "after_commit"}
REQUIRED = tuple(f"{r}:{lab}" for r in RULES for lab in ("approve", "armed", "unavailable", "replay-same", "replay-new"))


def gen_step(env, ch, attacker: str, rule: str) -> dict | None:
    """None -> caller falls back to a legit step (no approval-needing request, or ledger not quiet)."""
    if any(v > 0 for v in env.approvals.values()) or env.crashed:
        return None
    ops = approval_rules._approval_ops(env)  # noqa: SLF001
    if not ops:
        return None
    for cand in ch.choice([ops, ops[::-1]]):
        args = approval_rules._needs_args(env, ch, attacker, cand)  # noqa: SLF001
        if args is None:
            continue
        approver = approval_rules._approver(env, attacker, cand["name"], args, valid=True)  # noqa: SLF001
        if approver is None:
            continue
        me = next(p for p in env.principals() if p["id"] == attacker)
        via = ch.choice(["call_tool", "direct"]) if cand["name"] in env.tools(attacker) else "direct"
        return {"rule": rule, "attacker": attacker, "via": via, "op": cand["name"], "args": args,
                "obo": me["delegated_by"] if me["delegated_by"] and ch.chance(0.5) else None,
                "tok": {"kind": "valid", "sub": attacker}, "extra": {"requester": attacker, "approver": approver}}
    return None


def _commit(env, step, label, rid, point=None, clean=False):
    a = step["attacker"]
    return env.call(rule=f"{step['rule']}:{label}", via=step["via"], token=env.token(a), subject=a,
                    operation=step["op"], args=copy.deepcopy(step["args"]), on_behalf_of=step["obo"], request_id=rid,
                    tags={"approval"}, clean=clean, crash_point=point)


def exe(env, step: dict) -> list[dict]:
    rule, ap = step["rule"], step["extra"]["approver"]
    rid = lambda t: f"rq-{env.tag}-{env.n}-{t}"  # noqa: E731
    first = rid("k1")
    recs = [env.approve(rule=f"{rule}:approve", token=env.token(ap), approver=ap, requester=step["attacker"],
                        operation=step["op"], args=copy.deepcopy(step["args"]), on_behalf_of=step["obo"],
                        tags={"approval"})]
    point = POINT[rule]
    try:
        env.dep.arm_crash(point)
    except Exception as exc:  # noqa: BLE001
        recs.append({**_unsupported(step, exc)})
        return recs
    recs.append(_commit(env, step, "armed", first, point))
    if not env.crashed:  # not reached: clear the arm; the approval stays in the oracle ledger and is judged ordinarily
        env.disarm()
        return recs
    recs.append(_commit(env, step, "unavailable", rid("k2")))
    env.restart()
    recs.append(_commit(env, step, "replay-same", first, clean=(point == "before_commit")))
    recs.append(_commit(env, step, "replay-new", rid("k3")))
    return recs


def _unsupported(step, exc) -> dict:
    from .crash_rules import _unsupported as base
    return base(None, step, exc)[0]
