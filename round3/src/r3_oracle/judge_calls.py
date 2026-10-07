"""Per-call classification for judge_v2: refusals, progress, linearizability, authority_used (A1, A3, PROT-H24 s4/s8).

Legality of a call is evaluated at the two extreme linearizations consistent with real time: S_pre (every transaction
owned by a call that RETURNED before this call was invoked) and S_post (S_pre plus every overlapping authority change),
at the ticks read by the harness around the call. legal_all = legal at every one of them (R24-7 'in EVERY linearization'),
legal_any = legal at some (a refusal is then a legitimate race outcome)."""
from __future__ import annotations

from bisect import bisect_left

from . import ops_model
from .authority_v2 import INF, RefAuthority

AUTH_KINDS = ("delegate", "revoke", "set_authority")


def _legal(c, ra: RefAuthority, snap: dict, tick: int, ops):
    """(legal, expected Verdict-like (status, reason))."""
    k = c["kind"]
    if k == "delegate":
        v = ra.issue_delegate(c["edge"], INF, tick)
        return v.ok, (v.status, v.reason)
    if k == "revoke":
        v = ra.issue_revoke(c["actor"], c["edge_id"], INF)
        return v.ok, (v.status, "already" if v.reason == "already" else v.reason)
    if k == "set_authority":
        return True, ("OK", "")
    from .judge_v2 import _effect_outcome, _res
    dec = ra.decide(c["actor"], c["obo"], c["op"], _res(ops, c), None, tick)
    if not dec.allow:
        return False, ("DENIED", dec.reason)
    out = _effect_outcome(ops, ra, c, snap, tick, dec)
    return out.kind == ops_model.COMMIT and bool(out.effects), None  # a business-rule refusal: reason text is the variant's


def _positions(c, i_of, tx_calls, states, snaps):
    """(S_pre, [snapshots], S_post) for call c. The extra snapshot is the world after every overlapping transaction of
    another call (any order of overlapping effects is a consistent linearization); skipped if it would contain c's own."""
    pre = -1
    for j, (o, _) in enumerate(tx_calls):
        if o is not None and o["n"] != c["n"] and o["ret"] < c["inv"]:
            pre = j
    s_pre = states[pre + 1]
    post, jmax = s_pre, None
    own = i_of.get(c["n"])
    for j in range(pre + 1, len(tx_calls)):
        o, evt = tx_calls[j]
        if o is None or o["n"] == c["n"]:
            continue
        if o["inv"] < c["ret"] and c["inv"] < o["ret"]:
            jmax = j
            if evt is not None:
                post = post.apply(evt)
    after = [snaps[jmax + 1]] if jmax is not None and (own is None or own > jmax) else []
    return s_pre, [snaps[pre + 1], *after], post


def classify_calls(calls, res, txs, tx_calls, states, snaps, ops, diverged=False):
    idx = {o["n"]: j for j, (o, _) in enumerate(tx_calls) if o is not None}
    by_rid = {c["rid"]: c for c in calls if c["kind"] == "request" and c["n"] in idx and c.get("rid")}
    advances = [c for c in calls if c["kind"] == "advance"]
    for c in calls:
        r = res[c["n"]]
        cl = r["classes"]
        if c["kind"] == "advance":
            continue
        if c.get("unsupported"):
            cl.append("unsupported")
            continue
        if c.get("timeout"):
            cl.append("world_lock_timeout")
            continue
        if c["kind"] == "authority_used":
            _used(c, cl, by_rid, idx, txs, tx_calls, states, res, ops, diverged)
            continue
        s_pre, snap_list, s_post = _positions(c, idx, tx_calls, states, snaps)
        ticks = {c.get("tick_inv", 0), c.get("tick_ret", 0)}
        legal, exp = [], []
        for ra in (s_pre, s_post):
            for snap in snap_list:
                for t in ticks:
                    ok, exp_ = _legal(c, ra, snap, t, ops)
                    legal.append(ok)
                    exp.append(exp_)
        all_, any_ = all(legal), any(legal)
        already = all(e is not None and e[1] == "already" for e in exp)  # OK without a mark: nothing to commit
        r["must"] = bool(all_ and not already and not c.get("replay") and not c.get("crash") and c["status"] != "UNKNOWN")
        r["legal_any"] = any_
        _outcome(c, r, cl, all_, any_, exp)
        if not cl:
            cl.append("ok")
    _linearizable(calls, res, idx, tx_calls, advances)


def _outcome(c, r, cl, all_, any_, exp):
    committed, st, k = r["committed"], c["status"], c["kind"]
    if c.get("crash") and st == "UNKNOWN":
        if c["crash"] == "before_commit" and committed:
            cl.append("forbidden_effect")
        elif c["crash"] == "after_commit" and not committed and all_:
            cl.append("authority_ack_without_commit" if k in AUTH_KINDS else "progress_loss")
        return
    if committed or c.get("replay") or (st == "UNAVAILABLE" and c.get("reason") == "crashed"):
        return  # UNAVAILABLE-after-crash is the protocol's answer (PROT-H23-A8), not a refusal decision
    if st == "OK":
        if k in AUTH_KINDS and not all(e and e[1] == "already" for e in exp):
            cl.append("authority_ack_without_commit")
        elif k == "request" and any_:
            cl.append("progress_loss")
        return
    if any_:
        cl.append("progress_loss" if all_ else "race_refusal_ok")
    elif all(e is not None for e in exp) and (k in AUTH_KINDS or c.get("obo") is not None) \
            and (st, c.get("reason")) not in {tuple(e) for e in exp}:
        cl.append("explicit_reason_mismatch")


def _linearizable(calls, res, idx, tx_calls, advances):
    marked = sorted((c for c in calls if c["n"] in idx), key=lambda c: c["ret"])
    rets = [c["ret"] for c in marked]
    pm, best = [], (-1, None)
    for c in marked:  # prefix max of the transaction index, with the call that owns it
        best = max(best, (idx[c["n"]], c["n"])) if best[1] is not None else (idx[c["n"]], c["n"])
        pm.append(best)
    bad = set()
    for y in marked:
        k = bisect_left(rets, y["inv"])  # calls that returned strictly before y was invoked
        if k and pm[k - 1][0] > idx[y["n"]]:
            bad.add(pm[k - 1][1])
        for a in advances:
            if a["ret"] < y["inv"] and a.get("to") is not None and res[y["n"]]["tick"] is not None \
                    and res[y["n"]]["tick"] < a["to"]:
                bad.add(y["n"])
    for n in bad:
        res[n]["classes"].append("linearizability_violation")


def _used(c, cl, by_rid, idx, txs, tx_calls, states, res, ops, diverged=False):
    """R24-6: path in oracle valid_paths at that commit point, version == oracle digest, seq/tick == ground truth."""
    from .judge_v2 import _res
    body, owner = c.get("body") or {}, by_rid.get(c["rid"])
    if owner is None:
        if c["status"] == "OK":
            cl.append("historical_mismatch")  # authority claimed for a request that never committed
        return
    r = res[owner["n"]]
    if (r["oracle"] or {}).get("allow") is False:  # the effect itself is already classified; its authority_used is derived
        cl.append("ok")
        return
    j = idx[owner["n"]]
    ra = states[j]
    dec = ra.decide(owner["actor"], owner["obo"], owner["op"], _res(ops, owner), r["seq"], r["tick"])
    paths = {tuple(p) for p in dec.valid_paths} or {()}
    good = (c["status"] == "OK" and body.get("world_seq") == r["seq"] and body.get("tick") == r["tick"]
            and tuple(body.get("path") or ()) in paths
            and (diverged or body.get("authority_version") == ra.digest_at(r["seq"]))
            and body.get("on_behalf_of") == owner["obo"])
    cl.append("ok" if good else "historical_mismatch")
