"""G5-E33: the world_log commit marks are cross-checked against the anchor log and the ExternalWorld ledger (PROT-H29 1.6 / Q11), evaluated at the
END of every non-boundary sequence (after RC2). Pure over the raw record + the closed anchor index + the oracle's intents.

Rules (what is observable, no variant code is read):
 key      A commit mark is keyed by data.request_id; a variant anchors a governed decision with decision_id == request_id (both real variants,
          every mark of every dev run). A mark WITHOUT a non-blank string request_id has no decision_id the harness can name, so it can never be
          matched: -> unanchored_commit (no mark of that shape occurs in any recorded run; G5-E12 "commit without request_id" is not observable).
 (a)      mark -> an anchor entry of THIS sequence's stream (own worker anchor, G5-E30e) with that decision_id, else unanchored_commit.
 (b)      anchor -> mark. The anchor entry is (stream, seq, decision_id, root): it does NOT say OK or DENIED (both variants anchor DENIED decisions
          too, and approvals as "approve:<n>"). Residual gap: only the subset the transcript can tell is checked - an entry whose decision_id is a
          request_id that got an OK reply (any copy) must have a commit mark, else anchored_without_commit.
 (c)      ledger row -> mark: every applied row of this deployment belongs (correlation "<rid>#<i>") to a request with a commit mark, else
          forbidden_effect. mark -> ledger: every committed intent of the oracle's decision has an applied row or at least one ExternalWorld
          attempt (audit / unverified row of its correlation) after RC2 dispatch + reconcile, else committed_effect_missing.
 (d)      world_log rewritten: observations of the harness (wlog) - seq gap, or a prefix that changed between two reads."""
from __future__ import annotations

from r3_oracle import extoracle
from r3_shared.extadapter import parse_correlation

REQ_KINDS = ("request", "redeliver")


EXEMPT_STATES = ("RECONCILED_FAILED", "UNKNOWN")


def _correlations(r) -> set:
    """Every form the shared ExternalWorld records a correlation (G5-E34 b): the row's own `correlation` (attributed rows), the unverified claim's
    `correlation` and its `caveats` pairs [name, value] (extworld_core._claim; `unavailable` refusals attribute nothing, G5-E4 / P1g-3)."""
    out = {r.get("correlation")}
    cl = r.get("claim") or {}
    out.add(cl.get("correlation"))
    for cav in cl.get("caveats") or []:
        if isinstance(cav, (list, tuple)) and len(cav) == 2 and cav[0] == "correlation":
            out.add(cav[1])
    return {c for c in out if isinstance(c, str) and c}


def _hit(row, cls, detail):
    row["classes"].setdefault(cls, []).append(detail)


def _rid(m):
    r = m["data"].get("request_id")
    return r if isinstance(r, str) and r.strip() else None


def check_wl(R, row):
    """(d) + the presence rule: a record with a readable world must carry its observations (missing evidence is never a pass)."""
    wl = R.get("wl")
    if R.get("world") is not None and not any(o.get("where") == "end" and "error" not in o for o in (wl or [])):
        row["harness"].append("world_log_unobserved")
        return
    for o in wl or []:
        if o.get("gap"):
            _hit(row, "recovery_divergence", {"rc": o["where"].upper(), "what": "world_log_rewritten", "t": o["t"], "why": "seq gap", "gap": o["gap"]})
        if o.get("prefix_changed"):
            _hit(row, "recovery_divergence", {"rc": o["where"].upper(), "what": "world_log_rewritten", "t": o["t"], "why": "prefix read earlier changed",
                                              "prev_n": o.get("prev_n"), "n": o["n"]})


def check_marks(R, ctx, row, ev, dl, intents, oc, window_ok=True):
    w = R.get("world")
    if w is None:
        return                                                    # B4 / unreadable store: nothing to cross-check
    marks = w["marks"]
    stream = R.get("stream")
    marked = {_rid(m) for m in marks} - {None}
    if stream:
        anchored = {d for (s, d) in ctx.anchor_of(R) if s == stream}
        for m in marks:
            rid = _rid(m)
            if rid is None or rid not in anchored:
                _hit(row, "recovery_divergence", {"rc": "END", "what": "unanchored_commit", "rid": rid, "world_seq": m["seq"],
                                                  "why": "no anchor entry with decision_id == request_id" if rid else "commit mark without a request_id"})
        ok_rids = {e["rid"] for e in ev if e["k"] in REQ_KINDS and e.get("rid") and (e.get("res") or {}).get("status") == "OK"}
        for rid in sorted(ok_rids & anchored - marked):
            _hit(row, "recovery_divergence", {"rc": "END", "what": "anchored_without_commit", "rid": rid,
                                              "why": "anchor entry for a request answered OK, no commit mark in world_log"})
    for r in dl["effects"]:                                       # ledger row -> mark
        try:
            rid = parse_correlation(r["correlation"])[0]
        except (ValueError, KeyError, TypeError):
            rid = None
        if rid not in marked:
            _hit(row, "forbidden_effect", {"ledger_seq": r["seq"], "rid": rid, "correlation": r.get("correlation"),
                                           "why": "ExternalWorld effect row of this deployment without a commit mark"})
    if not any(e["k"] == "rc2" for e in ev) or any(e["k"] in ("tamper", "canonical_state_lost") for e in ev):
        return                                                    # after RC2 only; a history tamper / store loss is judged by the boundary + F8 rules
    if (R.get("seq_def") or {}).get("byz"):
        return                                                    # G5-E35 B3: Byzantine-adapter intents are judged by the H28 catalogue rules, not by (c)
    att = {}
    for r in dl["audit"] + dl.get("unverified", []):
        for c in _correlations(r):
            att.setdefault(c, set()).add(r["seq"])
    for rid in sorted(intents):
        if rid not in marked:
            continue
        for I in intents[rid]:
            if any(extoracle.key5(r) == extoracle.key5(I) for r in dl["effects"]) or att.get(I["correlation"]):
                continue
            st = oc["oracle"].get((rid, I["effect_index"]), ("PENDING",))[0]
            if st in EXEMPT_STATES:                               # G5-E34 (b): terminal RECONCILED_FAILED / admitted in-doubt state (E33(c) as written)
                continue
            _hit(row, "recovery_divergence", {"rc": "END", "what": "committed_effect_missing", "rid": rid, "effect": I["effect_index"],
                                              "system": I["system"], "oracle_state": st, "why": "committed intent never dispatched (no row, no attempt)"})
