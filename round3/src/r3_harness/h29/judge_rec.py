"""Recovery checks of the H29 judge (R29-9 RC1 determinism, R29-10 RC1 admissibility, R29-11 RC2 equality + redelivery). The prediction comes
from r3_oracle.recoverymodel over the oracle's own intents and the closed ledger; the variant's views are only COMPARED."""
from __future__ import annotations

from r3_oracle import continuity as C
from r3_oracle import recoverymodel as RM
from r3_shared.extadapter import canon_json
from r3_shared.recovery import RecoveryFormError, validate_recovery_view

from . import judge_ext as JE


def _canon_ok(v):
    try:
        return canon_json(validate_recovery_view(v)), None
    except (RecoveryFormError, TypeError, KeyError) as exc:
        return None, str(exc)[:160]


def _marks_view(marks):
    return [{"request_id": m["data"].get("request_id"), "world_seq": m["seq"], "authority_version": m["data"].get("authority_version"),
             "tick": m["tick"]} for m in marks]


def judge_recovery(R: dict, events: list, versions: list, intents: dict, tick0: dict, dl: dict, systems: dict, window: int,
                   rep_open: list, reads: dict, fault_at, anchor=None) -> dict:
    out = {"rc1": [], "rc2": [], "checks": 0, "passes": 0, "classes": {}, "unsupported": 0, "restricted_io": []}

    def hit(cls, detail):
        out["classes"].setdefault(cls, []).append(detail)

    for e in (x for x in events if x["k"] == "rc1"):
        T = e["resume"]
        rec = {"resume": T, "determinism": None, "admissible": None, "detail": []}
        if not e["a_started"]:
            rec["detail"].append("host A did not start")
            out["rc1"].append(rec)
            continue
        ca, ea = _canon_ok(e["view_a"]) if e["view_a"] is not None else (None, e["err_a"])
        cb, eb = _canon_ok(e["view_b"]) if e["view_b"] is not None else (None, e["err_b"])
        if ea and "NotImplementedError" in str(ea) or "not implemented" in str(ea):
            out["unsupported"] += 1
            out["rc1"].append(rec)
            continue
        out["checks"] += 2
        det = ca is not None and ca == cb
        rec["determinism"] = det
        if det:
            out["passes"] += 1
        else:
            hit("recovery_nondeterministic", {"resume": T, "a": ea or "view", "b": eb or "view", "diff": RM.view_diff(e["view_a"] or {}, e["view_b"] or {})[:6]})
        marks = _marks_view(e["marks"])
        exp = {}
        for rid, ints in intents.items():
            if rid not in {m["request_id"] for m in marks}:
                continue
            for mode in (False, True):
                sub = {rid: [rd for rd in reads.get(rid, []) if rd["t"] < T and (mode or rd.get("err") != "no_reply")]}
                o = JE.eval_outcomes(sub, {rid: ints}, tick0, dl, systems, window, fault_at)
                for I in ints:
                    k = (rid, I["effect_index"])
                    st, cf = (o["oracle"][k][0], o["oracle"][k][1]) if k in o["oracle"] else RM.initial_state(I)
                    cur = exp.setdefault(k, {"admissible_states": {"PENDING", "UNKNOWN"}, "confidence": cf, "system": I["system"]})
                    cur["admissible_states"].add(st)
        viol = RM.rc1_admissible(e["view_a"] or {}, marks, exp, versions, T) if ca is not None else ["view invalid: " + str(ea)]
        rec["admissible"] = not viol
        if not viol:
            out["passes"] += 1
        for v in viol:
            hit("stale_authority_after_restart" if "stale_authority_after_restart" in v else "recovery_divergence", {"rc": "RC1", "resume": T, "what": v})
        if e.get("anchor_head_before") is not None and e.get("anchor_head_after") != e.get("anchor_head_before"):
            out["restricted_io"].append({"resume": T, "what": "anchor appended during the restricted phase",
                                         "before": e["anchor_head_before"], "after": e["anchor_head_after"]})
        out["rc1"].append(rec)
    for e in (x for x in events if x["k"] == "rc2"):
        rec = {"t_probe": e["t_probe"], "equal": None, "redelivery": None, "diff": []}
        if e["view"] is None:
            out["checks"] += 1
            hit("recovery_divergence", {"rc": "RC2", "what": f"no recovery_view: {e.get('err')}"})
            out["rc2"].append(rec)
            continue
        out["checks"] += 1
        marks = _marks_view(e["marks"])
        o = JE.eval_outcomes(reads, intents, tick0, dl, systems, window, fault_at)
        views = JE.intent_views({r: i for r, i in intents.items() if r in {m["request_id"] for m in marks}}, o["oracle"], dl)
        pred = RM.predict_view(marks, views, versions, e["t_probe"], rep_open)
        pred["authority"]["lease_until"] += R["base"]               # the view carries the service's ABSOLUTE tick; the oracle works relative
        diff = RM.view_diff(pred, e["view"])
        rec["diff"], rec["equal"] = diff[:12], not diff
        if not diff:
            out["passes"] += 1
        else:
            stale = [d for d in diff if d.startswith("authority")]
            if stale and e["view"].get("authority", {}).get("version") not in (None, pred["authority"]["version"]):
                hit("stale_authority_after_restart", {"rc": "RC2", "diff": stale})
            rest = [d for d in diff if not d.startswith("authority") or d not in stale]
            if rest or not stale:
                hit("recovery_divergence", {"rc": "RC2", "diff": diff[:12]})
        beh = e["marks_after"] == e["marks_before"]
        rec["redelivery"] = beh
        if not beh:
            hit("recovery_divergence", {"rc": "RC2", "what": "redelivery created a new commit", "before": e["marks_before"], "after": e["marks_after"]})
        new_rows = [r for r in dl["effects"] if r["tick"] == e["t_redeliver"]]
        if new_rows and e["redelivered"]:
            hit("recovery_divergence", {"rc": "RC2", "what": "redelivery created ledger rows", "rows": [r["seq"] for r in new_rows][:5]})
        miss = [m["data"].get("request_id") for m in e["marks"] if isinstance(m["data"].get("request_id"), str)
                and R.get("stream") and (R["stream"], m["data"]["request_id"]) not in (anchor or ())]
        if miss and anchor is not None:
            hit("unanchored_ack", {"rc": "RC2", "what": "world commit still unanchored at RC2 (G5-E12)", "rids": miss[:5]})
        out["rc2"].append(rec)
    _redelivery_decisions(R, events, out, hit)
    return out


DECISION_PLANE = ("OK", "DENIED", "INVALID")


def _redelivery_decisions(R, events, out, hit) -> None:
    """G5-E35 B1 / R29-11 / G5-E16: redelivering a COMMITTED request_id returns the original decision: the decision-plane status of its first
    decided reply and, for a non-OK status, the same reason. Judged for every RC2 redelivery (tag rc2_redeliver; any other status, UNAVAILABLE included,
    is a difference) and for in-sequence redeliveries that were decided (a dependency failure there is judged by R29-7, not here). An F8 tamper
    sequence is exempt: R27-5 (non-OK with zero effect, or exactly untampered behaviour) applies instead. Counts in the recovery equality ratio."""
    if any(e["k"] in ("tamper", "canonical_state_lost") for e in events):
        return
    committed = {m["data"].get("request_id") for m in ((R.get("world") or {}).get("marks") or [])}
    orig = {}
    for e in events:
        if e["k"] not in ("request", "redeliver") or e.get("rid") not in committed or not e.get("res"):
            continue
        rid, st = e["rid"], e["res"]["status"]
        if rid not in orig:
            if st in DECISION_PLANE:
                orig[rid] = (st, (e["res"].get("body") or {}).get("reason") if st != "OK" else None, e["n"])
            continue
        if e["k"] != "redeliver" or e["n"] <= orig[rid][2]:
            continue
        rc2 = e.get("tag") == "rc2_redeliver"
        if not rc2 and st not in DECISION_PLANE:
            continue
        body = e["res"].get("body") or {}
        got = (st, body.get("reason") if st != "OK" else None)
        out["checks"] += 1
        if got == orig[rid][:2]:
            out["passes"] += 1
        else:
            hit("recovery_divergence", {"rc": "RC2" if rc2 else "REDELIVERY", "what": "redelivery_decision_changed", "rid": rid, "t": e["t"],
                                        "original": list(orig[rid][:2]), "got": list(got)})
