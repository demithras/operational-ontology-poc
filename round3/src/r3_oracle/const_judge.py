"""H25 run judge (ORACLE-AND-HARNESS-G3 A1/A3): walk the world_log in commit order with the Constitution oracle, classify
every harness call. CallResult is never read as ground truth: `status`/`reason` strings on a call record are labels used
only for refusals and acknowledge-without-commit checks. Inputs are plain data (see CALL_FIELDS)."""
from __future__ import annotations

import copy

from r3_shared import constitutional as K
from r3_shared.world import diff as world_diff

from . import const_refusal as R
from . import logreplay, ops_model
from .const_static import static_errors
from .constitution import Constitution

CALL_FIELDS = ("n", "kind", "rid", "actor", "token_ok", "action", "op", "args", "obo", "doc", "spec", "to", "status",
               "reason", "inv", "ret", "tick_inv", "tick_ret", "crash", "replay", "unsupported", "timeout", "raised",
               "approved")
MARK_KEY = {"propose": ("case",), "judge": ("case", "stage", "judge"), "appeal": ("case", "by"), "end": ("emergency",)}


def claim(calls, t, used, committed_rid):
    """The call a transaction belongs to: commit-mark request_id first, else governance/authority payload keys."""
    rid = t["commit"]["data"].get("request_id") if t["commit"] else None
    pool = sorted((c for c in calls if c["n"] not in used and c["kind"] not in ("advance", "approve")),
                  key=lambda c: (c.get("status") not in ("OK", "UNKNOWN"), c["inv"]))
    if rid is not None:
        cand = [c for c in pool if c.get("rid") == rid]
        if cand:
            return cand[0]
    gov = [r for r in t["marks"] if r["ref"] == "governance"]
    auth = [r for r in t["marks"] if r["ref"] == "authority"]
    if gov:
        d = gov[0]["data"]
        for c in pool:
            if c["kind"] == "set_governance" and d.get("op") == "set_governance" and d.get("version") == K.digest(c["doc"]):
                return c
            a = c.get("action")
            if c["kind"] == "constitutional" and isinstance(a, dict) and a.get("kind") == d.get("op") and a["kind"] in MARK_KEY:
                if all(d.get(k) == (a.get(k) if k != "judge" and k != "by" else c["actor"]) for k in MARK_KEY[a["kind"]]):
                    return c
    if auth:
        for c in pool:
            if c["kind"] == "set_authority":
                return c
    return None


def _mark(t):
    g = [r for r in t["marks"] if r["ref"] == "governance"]
    return g[0] if g else None


def _emerg_spec(base: dict, who: str, op: str) -> dict:
    s = copy.deepcopy(base)
    s["grants"].append({"id": "__emergency", "effect": "allow", "operation": op, "principal": {"id": who},
                        "resource": {"any": True}, "delegable": False, "origin": "neutral-extension"})
    return s


def op_outcome(C: Constitution, run: dict, snap: dict, tick: int, approved: bool):
    base = _emerg_spec(C.base, run["subject"], run["op"]) if run["emergency"] else C.base
    return ops_model.evaluate(C.ops, base, run["subject"], run["obo"], run["op"], run["args"], snap, tick,
                              approved=approved)


def _effects(C, run, v, snap, tick, c, t, res, snap_after):
    out = op_outcome(C, run, snap, tick, bool(c.get("approved")))
    measured = world_diff(snap, snap_after)
    expected = out.effects if out.kind == ops_model.COMMIT else []
    unexpected, missing = ops_model.match_records(expected, measured)
    if out.kind != ops_model.COMMIT:
        res["classes"].append("illegitimate_effect")
    elif unexpected or (measured and missing):
        res["classes"].append("illegitimate_effect")
    elif missing:
        res["classes"].append("progress_loss")
    res["effects"] = len(measured)


def _tx_constitutional(C, c, t, res, snap, tick, seq):
    mark = _mark(t)
    v = C.decide_action(c["actor"] if c.get("token_ok", True) else None, c["action"], seq, tick)
    res["oracle"] = {"status": v.status, "reason": v.reason}
    cls = res["classes"]
    kind = c["action"]["kind"]
    if v.status not in ("OK", "RUN"):
        cls.append("procedural_mismatch")
        if kind == "execute" and v.reason == "oracle_needed":
            cls.append("fabricated_judgment")
        if kind in ("execute", "act"):
            cls.append("illegitimate_effect")
        if kind == "act" and v.reason in ("emergency_expired", "out_of_emergency_scope", "not_grantee", "emergency_inactive"):
            cls.append("emergency_violation")
        return None, v
    if mark is None or mark["data"] != v.mark:
        cls.append("procedural_mismatch")
        res["mark_diff"] = {"expected": v.mark, "actual": None if mark is None else mark["data"]}
        if kind == "execute" and mark is not None:
            known = {j["rid"] for cs in C.s["cases"].values() for j in cs["judgments"]}
            if not set(mark["data"].get("basis", [])) <= known:
                cls.append("fabricated_judgment")
    return v.mark, v


def judge(calls, rows, C0: Constitution, snap0: dict, final_snap: dict | None, writers: frozenset) -> dict:
    txs = logreplay.group(rows)
    C, snap, used, committed_rid = C0, snap0, set(), {}
    states, snaps, seqs, idx_of_call = [C0], [snap0], [0], {}
    res = {c["n"]: {"n": c["n"], "kind": c["kind"], "classes": [], "seq": None, "tick": None, "committed": False,
                    "oracle": None} for c in calls}
    case: list[str] = []
    for t in txs:
        if t["tag"] == "seed":
            snap = logreplay.apply_rows(snap, t["canon"])
            snaps[-1] = snap
            continue
        c = claim(calls, t, used, committed_rid)
        gm = _mark(t)
        after = logreplay.apply_rows(snap, t["canon"])
        if any(r["writer"] not in writers for r in t["rows"] if r["kind"] in logreplay.CANON):
            case.append("writer_violation")
        if c is None:
            if gm or t["commit"] or t["authority"]:
                case.append("illegitimate_effect")
            elif t["canon"]:
                case.append("unlogged_write")
            if t["canon"] and not t["commit"]:
                case.append("unattributed_write")
        else:
            used.add(c["n"])
            r = res[c["n"]]
            seq = (gm or (t["authority"] or [None])[0] or t["commit"] or t["rows"][0])["seq"]
            r.update({"seq": seq, "tick": t["tick"], "committed": True})
            idx_of_call[c["n"]] = len(states)
            if c.get("rid") is not None and c["kind"] != "set_governance":
                if c["rid"] in committed_rid:
                    r["classes"].append("illegitimate_effect")  # PROT-H23 R5: a committed request_id never commits twice
                committed_rid[c["rid"]] = seq
            C = _apply_tx(C, c, t, r, snap, after, seq, t["tick"], case)
        snap = after
        states.append(C)
        snaps.append(snap)
        seqs.append(max([r_["seq"] for r_ in t["rows"]]))
    R.check_refusals(calls, res, states, snaps, seqs, idx_of_call, committed_rid, case)
    R.check_linearizability(calls, res, idx_of_call)
    if final_snap is not None and not logreplay.same_world(snap, final_snap):
        case.append("unlogged_write")
    return {"calls": res, "case_classes": sorted(set(case)), "final": C, "states": states}


def _apply_tx(C, c, t, r, snap, after, seq, tick, case):
    k = c["kind"]
    if k == "constitutional":
        mark, v = _tx_constitutional(C, c, t, r, snap, tick, seq)
        if v.status == "RUN":
            _effects(C, v.run, v, snap, tick, c, t, r, after)
        if v.status in ("OK", "RUN"):
            return C.apply({"kind": "action", "subject": c["actor"], "action": c["action"], "seq": seq, "tick": tick,
                            "rid": c["rid"]})
        return C
    if k == "set_governance":
        if static_errors(c["doc"], C.base, C.ops):
            r["classes"].append("invalid_doc_accepted")
            return C
        return C.apply({"kind": "set_governance", "doc": c["doc"], "seq": seq, "tick": tick})
    if k == "set_authority":
        return C.apply({"kind": "authority", "op": "set_authority", "payload": {"spec": c["spec"]}, "seq": seq, "tick": tick})
    if k == "request":
        _ordinary(C, c, r, snap, after, seq, tick)
        return C
    r["classes"].append("illegitimate_effect")
    return C


def _ordinary(C, c, r, snap, after, seq, tick):
    """An ordinary call_tool/direct that committed: a governed request must never (case_required); an ungoverned one
    is judged by the H23 model."""
    from . import const_eval as E
    op = ops_model.op_of(C.ops, c["op"])
    res = E.resources_for(C.ops, c["op"], c["args"])
    if C.doc is not None and E.covering(C.doc, c["op"], res):
        r["classes"].append("illegitimate_effect")
        return
    out = ops_model.evaluate(C.ops, C.base, c["actor"], c["obo"], c["op"], c["args"], snap, tick,
                             approved=bool(c.get("approved")))
    measured = world_diff(snap, after)
    expected = out.effects if out.kind == ops_model.COMMIT else []
    unexpected, missing = ops_model.match_records(expected, measured)
    if unexpected or (measured and missing) or op is None:
        r["classes"].append("illegitimate_effect")
