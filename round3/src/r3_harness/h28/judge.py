"""Classification of one (case, variant) from RAW records + the closed ledger, using only the ORACLE (r3_oracle.extoracle).
Variant CallResults are used for exactly two things the protocol makes legitimate: the decision STATUS (R28-11b compares it to the
oracle's) and the outcome records returned by reconcile() (compared to the oracle's state at the same observer snapshot).
Total and deterministic; never raises on a malformed record (it classifies it)."""
from __future__ import annotations

import json
from collections import defaultdict

from r3_oracle import extoracle

CLASSES = ("effect_outside_scope", "false_reconciled_success", "governance_in_adapter", "duplicate_effect", "outcome_mismatch",
           "progress_loss", "envelope_mismatch")
HARNESS = ("unsupported", "world_lock_timeout", "ext_transcript_mismatch", "generator_redraw_exhausted", "deploy_error")
GOV_SUB = ("adapter_influenced_decision", "oracle_denied_variant_ok", "adapter_artefact_consumed", "static_unresolved")
MARKERS = ("harness-fake",)           # authority artefacts the G2 adapter plants in its replies
MUTATION_KINDS = ("target_substitution", "payload_mutation")


class LedgerIndex:
    def __init__(self, ledger: dict):
        self.ledger = ledger
        self.eff, self.aud = defaultdict(list), defaultdict(list)
        for r in ledger["effects"]:
            self.eff[r["deployment"]].append(r)
        for r in ledger["audit"]:
            self.aud[r["deployment"]].append(r)

    def dep_ledger(self, dep: str) -> dict:
        return {"effects": self.eff.get(dep, []), "audit": self.aud.get(dep, [])}


def form_ok(o) -> bool:
    """Lenient P1f-6 form check: exact six keys + vocabulary; evidence only needs to be a list (G4-E6 strings vs P1f int schema gap)."""
    return (isinstance(o, dict) and set(o) == {"request_id", "effect_index", "system", "state", "confidence", "evidence"}
            and o["state"] in ("PENDING", "RECONCILED_SUCCESS", "RECONCILED_FAILED", "DIVERGED", "UNKNOWN")
            and o["confidence"] in ("full", "low") and isinstance(o["evidence"], list) and isinstance(o["effect_index"], int))


def _intents(R: dict) -> dict:
    return {q["rid"]: (q["tick"], q["intents"]) for q in R["requests"] if q["intents"] and not q["replay"]}


def eval_outcomes(R: dict, led: LedgerIndex, systems: dict) -> dict:
    """Replay every reconcile point with the oracle's outcome function; compare to what the variant returned."""
    dep, ints = R["dep"], _intents(R)
    dl = led.dep_ledger(dep)
    out = {"points": 0, "equal": 0, "mismatch": [], "false": [], "transcript_bad": 0, "finals": {}, "oracle_finals": {}, "observed": 0, "rules": [], "evidence_bad": []}
    prev: dict = {}
    prev_wm: dict = {}
    for rc in R["recon"]:
        rid, fault = rc["rid"], rc["fault"]
        if rc["error"] and rc["error"].startswith(("unsupported", "world_lock")):
            continue
        if rid not in ints:                                   # no external effect committed: reconcile must say unknown_request
            if any(q["rid"] == rid and q["status"] == "OK" and q["oracle"] != "OK" for q in R["requests"]):
                continue                                  # variant committed what the oracle denies: already governance_in_adapter
            out["points"] += 1
            if rc["status"] == "INVALID" and rc["reason"] == "unknown_request":
                out["equal"] += 1
            else:
                out["mismatch"].append({"rid": rid, "tick": rc["tick"], "why": f"phantom outcome: {rc['status']} {rc['reason']} {rc['error']}"})
            continue
        tick0, intents = ints[rid]
        unavailable = bool(fault) and fault["kind"] == "unavailable"
        lag = int(fault["k"]) if fault and fault["kind"] == "lagging" else 0
        snap = None if unavailable else extoracle.observer_view(dl, dep, systems, rc["watermark"], lag, rc["tick"])
        bad = rc["transcript"] if snap is None else [e for e in rc["transcript"] if not extoracle.transcript_matches(snap, e)]
        out["transcript_bad"] += len(bad)
        got = {o.get("effect_index"): o for o in rc["outcomes"]} if rc["status"] == "OK" and isinstance(rc["outcomes"], list) else None
        for I in intents:
            key = (rid, I["effect_index"])
            exp_s, exp_c, exp_e = extoracle.outcome_state(I, snap, prev.get(key, (None, []))[0], prev.get(key, (None, []))[1],
                                                          I["idempotency"], I["observability"], tick0 + R["window"], prev_wm.get(key), out["rules"])
            if snap is not None:
                prev_wm[key] = max(prev_wm.get(key, -1), snap["watermark"])
            prev[key] = (exp_s, exp_e)
            out["points"] += 1
            out["oracle_finals"][key] = exp_s
            g = None if got is None else got.get(I["effect_index"])
            if g is None or not form_ok(g):
                out["mismatch"].append({"rid": rid, "tick": rc["tick"], "why": f"no valid outcome for effect {I['effect_index']}: {rc['status']} {rc['reason']} {rc['error']}"})
                continue
            out["finals"][key] = g["state"]
            if g["evidence"] != exp_e:
                out["evidence_bad"].append({"rid": rid, "effect": I["effect_index"], "tick": rc["tick"], "got": g["evidence"], "oracle": exp_e})
            if (g["state"], g["confidence"]) == (exp_s, exp_c):
                out["equal"] += 1
                continue
            rec = {"rid": rid, "effect": I["effect_index"], "tick": rc["tick"], "got": [g["state"], g["confidence"]], "oracle": [exp_s, exp_c]}
            (out["mismatch"] if g["state"] != "RECONCILED_SUCCESS" else out["false"]).append(rec)
    return out


def count_duplicates(R: dict, led: LedgerIndex) -> int:
    dep, n = R["dep"], 0
    for _, (_, intents) in _intents(R).items():
        for I in intents:
            rows = [r for r in led.eff.get(dep, []) if extoracle.key5(r) == extoracle.key5(I)]
            n += max(0, len(rows) - 1) if I["idempotency"] in ("at_most_once", "exactly_once_required") else 0
    return n


def detection(R: dict, finals: dict, systems: dict) -> tuple[int, int]:
    """(attempted, detected) over full systems: the adapter (harness code) logged a write with (op, target, payload) != I's carrying I's cap."""
    att = det = 0
    seen = set()
    for _, (_, intents) in _intents(R).items():
        for I in intents:
            if I["observability"] != "full":
                continue
            mine = (I["operation"], I["target"], I["payload_digest"])
            hit = [a for a in R["attempts"] if a["request_id"] == I["request_id"] and a["effect_index"] == I["effect_index"]
                   and a["kind"] in MUTATION_KINDS and (a["op"], a["target"], a["payload_digest"]) != mine]
            if hit and (I["request_id"], I["effect_index"]) not in seen:
                seen.add((I["request_id"], I["effect_index"]))
                att += 1
                det += 1 if finals.get((I["request_id"], I["effect_index"])) == "DIVERGED" else 0
    return att, det


def _env_core(text: str):
    try:
        d = json.loads(text)
    except (TypeError, ValueError):
        return text
    if isinstance(d, dict) and isinstance(d.get("decision"), dict):
        return d["decision"]
    return d


def _rel(v, R: dict):
    """Twins run one after the other on one logical clock, so their ABSOLUTE ticks differ by construction (the case start_tick).
    Compare tick-valued fields relative to the case start_tick (as the world digest already does); the relative offset is still compared."""
    if isinstance(v, dict) and isinstance(v.get("body"), dict) and isinstance(v["body"].get("tick"), int):
        return {**v, "body": {**v["body"], "tick": v["body"]["tick"] - R.get("start_tick", 0)}}
    return v


def twin_diff(B: dict, T: dict) -> list[str]:
    """R28-11a: decision plane (status, reason, authority_used, canonical world digest, envelope decision part) byte-identical."""
    diffs = []
    bq = {(q["i"], q["replay"]): q for q in B["requests"]}
    tq = {(q["i"], q["replay"]): q for q in T["requests"]}
    if set(bq) != set(tq):
        diffs.append("request set")
    for k in sorted(set(bq) & set(tq)):
        for f in ("status", "reason", "authority_used"):
            if json.dumps(_rel(bq[k].get(f), B), sort_keys=True) != json.dumps(_rel(tq[k].get(f), T), sort_keys=True):
                diffs.append(f"req{k}.{f}")
    if B.get("world_digest") != T.get("world_digest"):
        diffs.append("world")
    env = lambda R: sorted({(e["request_id"], e["effect_index"], json.dumps(_env_core(e["envelope_text"]), sort_keys=True))  # noqa: E731
                           for log in R.get("recorder", {}).values() for e in log if e.get("envelope_text")})   # a SET: the byz adapter may re-submit
    if env(B) != env(T):
        diffs.append("envelope")
    return diffs


def envelope_mismatches(R: dict) -> list[dict]:
    """G4-E23 (Q13, R28-1): on NON-CRASH cases every recorded request's envelope_text must equal the auditor envelope of its decision.
    An absent auditor envelope counts as a mismatch only when the run had an anchor (history is then mandatory); crash cases are excluded (G4-E18)."""
    if R.get("crash"):
        return []
    aud, out = R.get("auditor_env", {}), []
    for s, log in sorted(R.get("recorder", {}).items()):
        for e in log:
            if e.get("request_id") not in aud:
                continue
            want = aud[e["request_id"]]
            if want is None and not R.get("anchor"):
                continue
            try:
                got = json.loads(e.get("envelope_text") or "")
            except (TypeError, ValueError):
                got = None
            if want is None or got != want:
                out.append({"rid": e["request_id"], "effect_index": e.get("effect_index"), "system": s,
                            "why": "no auditor envelope" if want is None else "envelope_text != auditor envelope"})
    return out


def governance(B: dict, T: dict | None) -> list[dict]:
    out = []
    probe = any(p in ("G1", "G2") for p in B["prims"])
    if T is not None and not (T["unsupported"] or T["deploy_error"]):
        d = twin_diff(B, T)
        if d:
            out.append({"sub": "adapter_influenced_decision", "detail": d})
    blob = json.dumps([[q.get("authority_used"), q.get("reason")] for q in B["requests"]], sort_keys=True, default=str)
    if any(m in blob for m in MARKERS):
        out.append({"sub": "adapter_artefact_consumed", "detail": "adapter-supplied authority artefact appears in the decision plane"})
    for q in B["requests"]:
        if q["oracle"] == "DENIED" and q["status"] == "OK":
            out.append({"sub": "adapter_artefact_consumed" if probe else "oracle_denied_variant_ok",
                        "detail": f"{q['operation']} by {q['subject']}: oracle {q['oracle_reason']}, variant OK"})
    return out


def progress(T: dict, finals: dict, crash: bool) -> list[dict]:
    """PROT-H28 s8: honest adapter, oracle OK, `full` system, no crash -> final state RECONCILED_SUCCESS (and the request must be OK)."""
    if crash:
        return []
    out = []
    for q in T["requests"]:
        if q["replay"] or q["oracle"] != "OK":
            continue
        if q["status"] != "OK":
            out.append({"rid": q["rid"], "why": f"oracle OK, variant {q['status']} {q['reason']}"})
        for I in q["intents"]:
            if I["observability"] == "full" and finals.get((q["rid"], I["effect_index"])) != "RECONCILED_SUCCESS":
                out.append({"rid": q["rid"], "why": f"final state {finals.get((q['rid'], I['effect_index']))} on {I['system']}"})
    return out


def judge_case(B: dict, T: dict | None, led: LedgerIndex, systems: dict, scope_rows: list) -> dict:
    """B = byz (or control) record, T = honest twin record (None for controls)."""
    row = {"case": B["case"], "variant": B["variant"], "domain": B["domain"], "system": B["system"], "prims": B["prims"],
           "classes": {}, "harness": [], "gov": [], "mismatch": [], "false": [], "progress": [], "envelope": [], "detect": [0, 0], "dups": 0,
           "points": 0, "equal": 0, "observed_effects": 0, "crash": bool(B.get("crash"))}
    recs = [B] + ([T] if T is not None else [])
    for R in recs:
        if R["unsupported"]:
            row["harness"].append("unsupported")
        if R["world_lock_timeout"]:
            row["harness"].append("world_lock_timeout")
        if R["deploy_error"]:
            row["harness"].append("deploy_error")
    if row["harness"]:
        return row
    ob = eval_outcomes(B, led, systems)
    row["mismatch"], row["false"] = ob["mismatch"], ob["false"]
    row["points"], row["equal"] = ob["points"], ob["equal"]
    if ob["transcript_bad"]:
        row["harness"].append("ext_transcript_mismatch")
    row["dups"] = count_duplicates(B, led)
    row["envelope"] = envelope_mismatches(B) + (envelope_mismatches(T) if T is not None else [])
    row["detect"] = list(detection(B, ob["finals"], systems))
    row["gov"] = governance(B, T)
    tw = ob if T is None else eval_outcomes(T, led, systems)
    if T is not None:
        row["mismatch"] += tw["mismatch"]
        row["false"] += tw["false"]
        row["points"] += tw["points"]
        row["equal"] += tw["equal"]
        if tw["transcript_bad"]:
            row["harness"].append("ext_transcript_mismatch")
    row["progress"] = progress(T or B, tw["finals"], bool(B.get("crash")))
    row["observed_effects"] = sum(1 for r in led.eff.get((T or B)["dep"], []) if systems["systems"][r["system"]]["observability"] != "none")
    row["scope_rows"] = [r["seq"] for r in scope_rows if r["deployment"] in (B["dep"], (T or {}).get("dep"))]
    c = row["classes"]
    if row["scope_rows"]:
        c["effect_outside_scope"] = len(row["scope_rows"])
    if row["false"]:
        c["false_reconciled_success"] = len(row["false"])
    if row["gov"]:
        c["governance_in_adapter"] = len(row["gov"])
    if row["dups"]:
        c["duplicate_effect"] = row["dups"]
    if row["mismatch"]:
        c["outcome_mismatch"] = len(row["mismatch"])
    if row["progress"]:
        c["progress_loss"] = len(row["progress"])
    if row["envelope"]:
        c["envelope_mismatch"] = len(row["envelope"])
    return row
