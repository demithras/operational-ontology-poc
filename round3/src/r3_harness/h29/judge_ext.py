"""Outcome plane of the H29 judge (R29-2, R29-5b/c, R29-7 outcome plane): replays every reconcile read with the oracle's P1f-6 function
(r3_oracle.extoracle, reused unchanged) over the closed ledger. Pure functions over raw records; total, deterministic."""
from __future__ import annotations

from r3_oracle import extoracle
from r3_oracle.recoverymodel import chain_count, initial_state

FINAL = ("RECONCILED_SUCCESS", "RECONCILED_FAILED", "DIVERGED")
VOCAB = ("PENDING", "RECONCILED_SUCCESS", "RECONCILED_FAILED", "DIVERGED", "UNKNOWN")


def dep_ledger(led, dep: str, base: int) -> dict:
    """The ledger rows of ONE deployment with RELATIVE ticks (the frame of the raw record)."""
    def rel(rows):
        return [{**r, "tick": r["tick"] - base} for r in rows]
    dl = led.dep_ledger(dep)
    # G5-E4: refused/unavailable rows carry no attribution; the deployment CLAIMED by the (unverified) cap places them in this deployment's frame
    unv = [r for r in led.ledger.get("unverified", []) if r["claim"].get("deployment") in (dep, dep + "~rc1b")]
    return {"effects": rel(dl["effects"]), "audit": rel(dl["audit"]), "unverified": rel(unv), "_dep": dep}


def form_ok(o) -> bool:
    return (isinstance(o, dict) and set(o) == {"request_id", "effect_index", "system", "state", "confidence", "evidence"}
            and o["state"] in VOCAB and o["confidence"] in ("full", "low") and isinstance(o["evidence"], list) and isinstance(o["effect_index"], int))


def eval_outcomes(reads_by_rid: dict, intents: dict, tick0: dict, dl: dict, systems: dict, window: int, fault_at) -> dict:
    """reads_by_rid: {rid: [reconcile events]}; intents: {rid: [I]} (oracle); tick0: {rid: commit tick}; fault_at(sys, a, b) -> bool.
    -> {points, equal, false: [], mis_outcome: [], other: [], oracle: {(rid, idx): (state, conf, ev, rule)}, got: {(rid, idx): state}}"""
    out = {"points": 0, "equal": 0, "false": [], "mis_outcome": [], "other": [], "oracle": {}, "got": {}}
    for rid, ints in sorted(intents.items()):
        prev, prev_wm = {}, {}
        for rd in reads_by_rid.get(rid, []):
            f = rd.get("fault")
            unavailable = bool(f) and f["kind"] == "unavailable"
            lag = int(f["k"]) if f and f["kind"] == "lagging" else 0
            snap = None if unavailable else extoracle.observer_view(dl, dl["_dep"], systems, rd["watermark"], lag, rd["t"])
            res = rd.get("res")
            got = {o.get("effect_index"): o for o in (res["body"].get("outcomes") or [])} if res and res["status"] == "OK" and isinstance(res.get("body"), dict) else None
            for I in ints:
                key = (rid, I["effect_index"])
                tr: list = []
                st, cf, ev = extoracle.outcome_state(I, snap, prev.get(key, (None, []))[0], prev.get(key, (None, []))[1], I["idempotency"],
                                                     I["observability"], tick0[rid] + window, prev_wm.get(key), tr)
                if snap is not None:
                    prev_wm[key] = max(prev_wm.get(key, -1), snap["watermark"])
                prev[key] = (st, ev)
                out["oracle"][key] = (st, cf, ev, tr[0] if tr else "")
                if rd.get("err") == "no_reply":
                    continue                                  # crashed in flight: the read may or may not have been applied
                out["points"] += 1
                g = None if got is None else got.get(I["effect_index"])
                faulted = unavailable or bool(lag) or fault_at(I["system"], tick0[rid], rd["t"])
                if g is None or not form_ok(g):
                    rec = {"rid": rid, "t": rd["t"], "why": f"no valid outcome: {(res or {}).get('status')} {rd.get('err')}"}
                    (out["mis_outcome"] if faulted and res and res["status"] in ("UNAVAILABLE", "DENIED") else out["other"]).append(rec)
                    continue
                out["got"][key] = g["state"]
                if (g["state"], g["confidence"]) == (st, cf):
                    out["equal"] += 1
                    continue
                rec = {"rid": rid, "effect": I["effect_index"], "t": rd["t"], "got": [g["state"], g["confidence"]], "oracle": [st, cf]}
                if g["state"] == "RECONCILED_SUCCESS":
                    out["false"].append(rec)
                elif g["state"] == "RECONCILED_FAILED" and st in ("PENDING", "UNKNOWN") and faulted:
                    out["mis_outcome"].append(rec)
                else:
                    out["other"].append(rec)
    return out


def duplicates(dl: dict, intents: dict) -> list:
    """R28-7: ledger rows beyond the class allowance for each intent -> [(rid, effect_index, extra_rows)]."""
    out = []
    for rid, ints in sorted(intents.items()):
        for I in ints:
            rows = [r for r in dl["effects"] if extoracle.key5({**r, "payload_digest": r["payload_digest"]}) == extoracle.key5(I)]
            n = max(0, len(rows) - 1) if I["idempotency"] in ("at_most_once", "exactly_once_required") else 0
            if n:
                out.append((rid, I["effect_index"], n))
    return out


def outside_scope(dl: dict, intents: dict) -> list:
    """R28-14: applied rows of this deployment equal to no I(d) of an oracle-committed decision."""
    want = {extoracle.key5(i) for ints in intents.values() for i in ints}
    return [r["seq"] for r in dl["effects"] if extoracle.key5(r) not in want]


def intent_views(intents: dict, oracle: dict, dl: dict) -> dict:
    """{(rid, idx): {system, chain_ids, state, confidence}} after the last applied read (initial state when none)."""
    out = {}
    for rid, ints in intents.items():
        for I in ints:
            k = (rid, I["effect_index"])
            st, cf = (oracle[k][0], oracle[k][1]) if k in oracle else initial_state(I)
            out[k] = {"system": I["system"], "chain_ids": chain_count(dl, I), "state": st, "confidence": cf}
    return out
