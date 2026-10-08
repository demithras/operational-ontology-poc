"""Judging calls that wrote nothing (refusals, stored results, rejected documents) and real-time ordering of commits
(ORACLE-AND-HARNESS-G3 A1: a refusal must match the oracle at SOME commit point between invoke and return; sequential
cases have exactly one). Pure; reads call records as labels only."""
from __future__ import annotations

from . import const_eval as E
from . import ops_model
from .const_static import static_errors

LOOSE = {ops_model.DENIED_RULE: ("DENIED", None), ops_model.INVALID: ("INVALID", None),
         ops_model.NEEDS_APPROVAL: ("DENIED", "approval_required"), ops_model.DENIED_AUTHORITY: ("DENIED", None),
         ops_model.UNKNOWN_OP: ("INVALID", None)}


def _bounds(c, calls, idx_of_call, n_states):
    lo, hi = 0, n_states - 1
    for b in calls:
        i = idx_of_call.get(b["n"])
        if i is None or b is c or b.get("ret") is None:
            continue
        if b["ret"] < c["inv"]:
            lo = max(lo, i)
        if c["ret"] < b["inv"]:
            hi = min(hi, i - 1)
    return lo, max(lo, hi)


def _expected(C, snap, seq, tick, c):
    """-> (status, reason|None) or ('COMMIT', None) for a constitutional/ordinary call at a commit point."""
    from . import const_judge as J
    if c["kind"] == "request":
        return _request_expected(C, snap, tick, c)
    v = C.decide_action(c["actor"] if c.get("token_ok", True) else None, c["action"], seq, tick)
    if v.status == "OK":
        return "COMMIT", None
    if v.status == "OK_STORED":
        return "OK", None
    if v.status == "RUN":
        out = J.op_outcome(C, v.run, snap, tick, bool(c.get("approved")))
        return ("COMMIT", None) if out.kind == ops_model.COMMIT else LOOSE[out.kind]
    return v.status, v.reason


def _request_expected(C, snap, tick, c):
    if not c.get("token_ok", True):
        return "DENIED", "token"
    op = ops_model.op_of(C.ops, c["op"])
    if op is None:
        return "INVALID", None
    res = E.resources_for(C.ops, c["op"], c["args"])
    if C.doc is not None and E.covering(C.doc, c["op"], res):
        ok = isinstance(c["args"], dict) and ops_model.schema_valid_args(op, c["args"])
        if ok and C.base_allows(c["actor"], c["obo"], c["op"], res, 10 ** 9, tick).allow:
            return "DENIED", "case_required"
        return "ANY", None
    out = ops_model.evaluate(C.ops, C.base, c["actor"], c["obo"], c["op"], c["args"], snap, tick,
                             approved=bool(c.get("approved")))
    return ("COMMIT", None) if out.kind == ops_model.COMMIT else LOOSE[out.kind]


def _fits(c, exp) -> bool:
    status, reason = exp
    if status == "ANY":
        return c["status"] in ("DENIED", "INVALID")
    if status == "COMMIT":
        return False
    return c["status"] == status and (reason is None or reason == c.get("reason"))


def check_refusals(calls, res, states, snaps, seqs, idx_of_call, committed_rid, case):
    for c in calls:
        if c["kind"] in ("advance", "approve") or c["n"] in idx_of_call:
            continue
        r = res[c["n"]]
        if c.get("unsupported"):
            r["classes"].append("unsupported")
            continue
        if c.get("timeout"):
            r["classes"].append("world_lock_timeout")
            continue
        if c["status"] in ("UNKNOWN", "UNAVAILABLE"):
            continue  # crash windows are judged by their transaction (if any) and by the retry
        if c["kind"] == "set_governance":
            bad = bool(static_errors(c["doc"], states[-1].base, states[-1].ops))
            if bad and not c.get("raised"):
                r["classes"].append("invalid_doc_accepted")
            elif not bad and c.get("raised"):
                r["classes"].append("procedural_mismatch")
            continue
        if c["kind"] == "set_authority":
            if c["status"] != "OK":
                r["classes"].append("procedural_mismatch")
            continue
        if c.get("rid") in committed_rid and c["status"] == "OK":
            continue  # stored result of a committed request_id: no second effect, same OK
        lo, hi = _bounds(c, calls, idx_of_call, len(states))
        pts = [(i, t) for i in range(lo, hi + 1) for t in sorted({c["tick_inv"], c["tick_ret"]})]
        exps = [_expected(states[i], snaps[i], seqs[i] + 1, t, c) for i, t in pts]
        fits = [e for e in exps if _fits(c, e)]
        r["oracle"] = {"expected": sorted({f"{s}:{x}" for s, x in exps})}
        if fits:
            if any(e[0] == "COMMIT" for e in exps):
                r["classes"].append("race_refusal_ok")  # refused in one linearization, allowed in another
            continue
        committable = any(e[0] == "COMMIT" for e in exps)
        act_kind = c["kind"] == "request" or (c.get("action") or {}).get("kind") in ("execute", "act")
        if committable and all(e[0] == "COMMIT" for e in exps) and act_kind:
            r["classes"].append("progress_loss")
        else:
            r["classes"].append("procedural_mismatch")


def check_linearizability(calls, res, idx_of_call):
    by = {c["n"]: c for c in calls}
    for a, ia in idx_of_call.items():
        for b, ib in idx_of_call.items():
            if a != b and by[a].get("ret") is not None and by[a]["ret"] < by[b]["inv"] and ia > ib:
                res[b]["classes"].append("linearizability_violation")
