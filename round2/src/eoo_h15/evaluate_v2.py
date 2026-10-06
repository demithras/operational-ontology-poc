"""H15 v2 evaluator: the frozen v1 evaluator (evaluate.py, unchanged) plus the v2 preregistration
(protocol/H15_V2_PREREG.json). Same contract clauses and thresholds; three amendments, all from the prereg:

* V1 (protocol validity) checks the v2 candidate pin (protocol/H15_V2_CANDIDATE.json unless overridden) and the hash
  of H15_V2_PREREG.json instead of the v1 candidate pin; every record must say candidate_surface = openpona2.
* R3 (indispensable sidecar) also holds when the meaning rule (bounded-vocabulary test) is violated, or when the
  sidecar audit did not report the meaning rule at all (then R3 is unknown, never False).
* S4 (0 indispensable sidecar fields) additionally requires the meaning rule to hold.
"""
from __future__ import annotations

import json
from pathlib import Path

from hdd.verdict import CommonEvaluation, evaluate_common

from . import evaluate as v1
from .util import ROOT, sha_file


def _pin(root: Path, candidate_pin) -> tuple[str | None, str]:
    p = Path(candidate_pin) if candidate_pin else root / "protocol/H15_V2_CANDIDATE.json"
    if not p.is_file():
        return None, str(p)
    return json.loads(p.read_text())["combined_sha256"], str(p)


def _set(rows: list, key: str, val) -> None:
    for r in rows:
        if r["id"] == key:
            r["value"] = val


def evaluate(exp_dir, root: Path = ROOT, candidate_pin=None) -> dict:
    d = Path(exp_dir)
    v = v1.evaluate(d, root)
    schema = json.loads((root / "schemas/evidence-record.schema.json").read_text())
    recs, pay, _ = v1._load(d, schema)
    fz = json.loads((root / "protocol/FREEZE.json").read_text())["protocol_sha256"]
    g0 = json.loads((root / "protocol/H15_GATE0.json").read_text())["combined_sha256"]
    cand, pin_path = _pin(root, candidate_pin)
    prereg = sha_file(root / "protocol/H15_V2_PREREG.json")
    bad = [f for f, r in recs.items()
           if (r["protocol_freeze_hash"], r.get("gate0_combined_sha256"), r.get("candidate_combined_sha256"),
               r.get("h15_v2_prereg_sha256"), r.get("candidate_surface")) != (fz, g0, cand, prereg, "openpona2")]
    pm = v["protocol_mismatches"]
    pm["records_with_wrong_hashes"] = bad
    pm["v2_candidate_pin"] = {"path": pin_path, "present": cand is not None, "combined_sha256": cand,
                              "h15_v2_prereg_sha256": prereg}
    protocol_valid = not bad and not pm["disagreeing_provenance"] and not pm["harness_self_check"]
    n = v["numbers"]
    side = pay.get("sidecar-audit.json") or {}
    mr = side.get("meaning_rule")
    meaning_ok = mr.get("ok") if isinstance(mr, dict) and isinstance(mr.get("ok"), bool) else None
    n["meaning_rule"] = None if mr is None else {k: mr.get(k) for k in (
        "ok", "verdict", "phrase_table_size", "distinct_phrases_total", "packages", "sizes", "sizes_over_bound")}
    pred = v["predicates"]
    r_old = {r["id"]: r["value"] for r in pred["reject_if"]}
    s_old = {r["id"]: r["value"] for r in pred["support_if"]}
    r3 = True if (r_old["R3"] is True or meaning_ok is False) else (None if (r_old["R3"] is None or meaning_ok is None) else False)
    s4 = (s_old["S4"] is True and meaning_ok is True) if s_old["S4"] is not None and meaning_ok is not None else None
    _set(pred["reject_if"], "R3", r3)
    _set(pred["support_if"], "S4", s4)
    _set(pred["invalid_if"], "V1", bool(bad))
    rvals = [r["value"] for r in pred["reject_if"]]
    svals = [r["value"] for r in pred["support_if"]]
    c = v["common"]
    common = CommonEvaluation(protocol_valid=protocol_valid, required_evidence_complete=c["required_evidence_complete"],
                              sample_sufficient=c["sample_sufficient"], reject_hit=any(x is True for x in rvals),
                              support_hit=all(x is True for x in svals))
    v["verdict"] = evaluate_common(common).value
    v["common"] = {"protocol_valid": common.protocol_valid, "required_evidence_complete": common.required_evidence_complete,
                   "sample_sufficient": common.sample_sufficient, "reject_hit": common.reject_hit,
                   "support_hit": common.support_hit}
    v["candidate_surface"] = "openpona2"
    v["protocol"] = {**v["protocol"], "candidate_combined_sha256": cand, "candidate_pin_path": pin_path,
                     "h15_v2_prereg_sha256": prereg}
    v["evaluator_v2_sha256"] = sha_file(Path(__file__))
    v["interpretation_notes"] = v["interpretation_notes"] + [
        "H15 v2 (protocol/H15_V2_PREREG.json): V1 checks the v2 candidate pin and the v2 prereg hash.",
        "Meaning rule (bounded vocabulary) enters R3 (reject) and S4 (support); unknown meaning-rule result keeps R3/S4 unknown."]
    return v


def evidence_surface(exp_dir) -> str:
    """'openpona2' if the evidence records were produced by the v2 candidate, else 'openpona'."""
    for f in v1.REQUIRED:
        p = Path(exp_dir) / f
        if p.is_file():
            try:
                return json.loads(p.read_text()).get("candidate_surface", "openpona")
            except Exception:  # noqa: BLE001
                continue
    return "openpona"
