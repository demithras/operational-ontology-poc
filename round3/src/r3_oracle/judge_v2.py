"""H24 run judge (ORACLE-AND-HARNESS-G2 A1): walk the world_log in seq order, decide every commit point with the
immutable reference authority and the H23 ops model, classify every harness call (A3 classes).

Inputs are plain data: `calls` = the harness schedule (dicts, see CALL_FIELDS), `rows` = WorldReader.log(), the initial
RefAuthority and snapshot. CallResult is never read: a call's `status`/`reason` strings are labels and are only used
for refusals and for the acknowledge-without-commit check. Clock values come only from tx.tick and the schedule."""
from __future__ import annotations

from r3_shared.world import diff as world_diff

from . import logreplay, ops_model
from .authority_v2 import INF, RefAuthority, event
from .logreplay import apply_rows

CALL_FIELDS = ("n", "kind", "rid", "actor", "obo", "op", "args", "edge", "edge_id", "spec", "to", "approved", "status",
               "reason", "inv", "ret", "tick_inv", "tick_ret", "crash", "replay", "unsupported", "timeout")
EDGE_CLASS = {"scope_amplification": "scope_amplification", "expiry_amplification": "scope_amplification",
              "delegation_cycle": "cycle_grant", "static_delegate": "cycle_grant", "unknown_parent": "cycle_grant",
              "unknown_principal": "cycle_grant", "duplicate_edge": "cycle_grant", "schema": "cycle_grant",
              "parent_invalid": "post_boundary_effect"}
OKS = ("OK",)


def _tx_authority_op(t: dict) -> dict | None:
    return t["authority"][0] if t["authority"] else None


def _claim(calls: list[dict], t: dict, used: set) -> dict | None:
    """The harness call a transaction belongs to: by commit-mark request_id, else by authority payload ids."""
    rid = t["commit"]["data"].get("request_id") if t["commit"] else None
    cands = [c for c in calls if c["n"] not in used and rid is not None and c.get("rid") == rid and c["kind"] != "advance"]
    # a call that crashed BEFORE its commit point has no transaction by protocol: a later send of the same id owns it
    cands.sort(key=lambda c: (c.get("crash") == "before_commit" and c.get("status") == "UNKNOWN", c["inv"]))
    if cands:
        return cands[0]
    a = _tx_authority_op(t)
    if a is not None:
        d = a["data"]
        for c in calls:
            if c["n"] in used:
                continue
            if (c["kind"] == "delegate" and d.get("op") == "delegate" and (d.get("edge") or {}).get("id") == (c["edge"] or {}).get("id")) \
                    or (c["kind"] == "revoke" and d.get("op") == "revoke" and d.get("edge_id") == c["edge_id"]) \
                    or (c["kind"] == "set_authority" and d.get("op") == "set_authority"):
                return c
    return None


def _res(ops, c) -> list:
    op = ops_model.op_of(ops, c["op"]) if c.get("op") else None
    return ops_model.resources_of(op, c["args"]) if op and isinstance(c.get("args"), dict) else []


def _effect_outcome(ops, ra: RefAuthority, c, snap, tick, dec):
    base = ra.view(None).base
    subj, obo = (c["obo"], None) if dec.valid_paths else (c["actor"], c["obo"])
    return ops_model.evaluate(ops, base, subj, obo, c["op"], c["args"], snap, tick, frozenset(), None,
                              approved=bool(c.get("approved")))


def judge(calls: list[dict], rows: list[dict], ra0: RefAuthority, snap0: dict, final_snap: dict | None, ops: dict,
          writers: frozenset) -> dict:
    txs = logreplay.group(rows)
    ra, snap, used = ra0, snap0, set()
    states, snaps, tx_calls, case = [ra0], [snap0], [], []
    res = {c["n"]: {"n": c["n"], "kind": c["kind"], "classes": [], "seq": None, "tick": None, "tx": None, "committed": False,
                    "oracle": None} for c in calls}
    committed_rid: dict = {}
    diverged = False
    pending_set = [c for c in calls if c["kind"] == "set_authority"]
    for i, t in enumerate(txs):
        c = _claim(calls, t, used)
        a = _tx_authority_op(t)
        if t["canon"] and t["commit"] is None:
            case.append("unattributed_write")
        if any(r["writer"] not in writers for r in t["rows"] if r["kind"] in logreplay.CANON):
            case.append("writer_violation")
        evt = None
        if c is None:
            if a is not None or t["commit"] is not None:
                case.append("forbidden_effect")  # a committed transaction nobody asked for
            tx_calls.append((None, None))
        else:
            used.add(c["n"])
            r = res[c["n"]]
            r.update({"seq": (a or t["commit"] or t["rows"][0])["seq"], "tick": t["tick"], "tx": t["tx"], "committed": True})
            seq, tick = r["seq"], t["tick"]
            if a is not None:
                evt = _authority_tx(c, a, t, ra, seq, tick, r, pending_set)
                diverged = diverged or bool(r["classes"])  # the variant's authority state no longer equals the oracle's
            elif t["commit"] is not None:
                _effect_tx(c, t, ra, snap, ops, seq, tick, r, committed_rid)
            tx_calls.append((c, evt))
            if evt is not None:
                ra = ra.apply(evt)
        snap = apply_rows(snap, t["canon"])
        states.append(ra)
        snaps.append(snap)
    from .judge_calls import classify_calls
    classify_calls(calls, res, txs, tx_calls, states, snaps, ops, diverged)
    if final_snap is not None and not logreplay.same_world(snap, final_snap):
        case.append("unlogged_write")
    return {"calls": res, "case_classes": sorted(set(case)), "final_authority": ra}


def _authority_tx(c, a, t, ra, seq, tick, r, pending_set):
    d = a["data"]
    if c["kind"] == "delegate":
        edge = d.get("edge") or c["edge"]
        if edge != c["edge"]:
            r["classes"].append("forbidden_effect")  # the variant changed the edge (clamped/rewritten): never allowed
        v = ra.issue_delegate(edge, seq, tick)
        r["oracle"] = {"verdict": v.status, "reason": v.reason}
        if not v.ok:
            r["classes"].append(EDGE_CLASS.get(v.reason, "forbidden_effect"))
            return None
        return event(seq, tick, "delegate", {"edge": edge})
    if c["kind"] == "revoke":
        v = ra.issue_revoke(c["actor"], c["edge_id"], seq)
        r["oracle"] = {"verdict": v.status, "reason": v.reason}
        if not v.ok:
            r["classes"].append("forbidden_effect")  # authority changed by someone who may not revoke / unknown edge
            return None
        return event(seq, tick, "revoke", {"edge_id": c["edge_id"]}) if v.reason != "already" else None
    if c["kind"] == "set_authority":
        return event(seq, tick, "set_authority", {"spec": c["spec"]})
    r["classes"].append("forbidden_effect")  # an authority mark on a call that is not an authority call
    return None


def _effect_tx(c, t, ra, snap, ops, seq, tick, r, committed_rid):
    if c["kind"] != "request":
        r["classes"].append("forbidden_effect")
        return
    if c["rid"] in committed_rid:  # PROT-H23 R5 / PROT-H24 s4: a committed request_id never gives a second effect
        r["classes"].append("forbidden_effect")
    committed_rid[c["rid"]] = seq
    after = apply_rows(snap, t["canon"])
    measured = world_diff(snap, after)
    dec = ra.decide(c["actor"], c["obo"], c["op"], _res(ops, c), seq, tick)
    r["oracle"] = {"allow": dec.allow, "reason": dec.reason, "paths": [list(p) for p in dec.valid_paths]}
    if not dec.allow:
        if measured:
            r["classes"].append("post_boundary_effect" if ra.was_ever_valid(c["actor"], c["obo"], c["op"], _res(ops, c), seq, tick)
                                else "forbidden_effect")
        return
    out = _effect_outcome(ops, ra, c, snap, tick, dec)
    expected = out.effects if out.kind == ops_model.COMMIT else []
    unexpected, missing = ops_model.match_records(expected, measured)
    if unexpected or (measured and missing):
        r["classes"].append("forbidden_effect")
    elif missing and not measured:
        r["classes"].append("progress_loss")
    r["effects"] = len(measured)
