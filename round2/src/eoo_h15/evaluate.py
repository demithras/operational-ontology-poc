"""Frozen H15 evaluator: evidence directory -> verdict.json (pure function of the evidence and the protocol files).

Missing / unreadable / inconsistent evidence can never produce SUPPORTED: it makes required_evidence_complete False.
A protocol mismatch makes the experiment INVALID. Every predicate of the contract is reported with the numbers behind it.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from hdd.verdict import CommonEvaluation, evaluate_common

from .evidence import REQUIRED, KIND
from .util import ROOT, canon, sha_file, sha_text

REGISTERED_DOMAINS = ("manufacturing", "project")
TARGET_CLASSES = ("drop_cardinality", "swap_function_action", "drop_authority_ref", "drop_version",
                  "accept_ambiguous_binding", "default_missing_type")
SURFACES = ("openpona", "dsl")

SUPPORT = {
    "S1": "100% of frozen real-domain contracts are semantically equivalent after OpenPona round-trip",
    "S2": "0 semantic-equivalence failures across at least 10,000 generated valid cases",
    "S3": "0 required new primitive tokens",
    "S4": "0 indispensable semantic sidecar fields",
    "S5": "100% of predeclared ambiguity/missing-type cases fail closed or remain unresolved",
    "S6": "All target mutation classes are detected",
}
REJECT = {
    "R1": "Any falsifier is observed in a frozen real-domain contract",
    "R2": "Any generated minimal counterexample demonstrates irreversible semantic loss in a required IR kind",
    "R3": "A new primitive token or indispensable semantic sidecar is required",
    "R4": "The compiler resolves an ambiguous input by silently inventing semantics (falsifier 5; mapped to reject)",
}
INCONCLUSIVE = {"I1": "Generated coverage is below 10,000 valid cases",
                "I2": "Either registered domain is not encoded completely"}
INVALID = {"V1": "Evidence records carry a protocol / Gate-0 / candidate hash different from the frozen files",
           "V2": "Evidence records disagree on commit / seed / corpus hash",
           "V3": "Harness self-check failed (mutation control not clean, oracle known-negative missed, patches leaked)"}


def _load(d: Path, schema: dict) -> tuple[dict, dict, list]:
    recs, pay, problems = {}, {}, []
    for f in REQUIRED:
        p = d / f
        if not p.is_file():
            problems.append(f"{f}: missing")
            continue
        try:
            r = json.loads(p.read_text())
            jsonschema.validate(r, schema)
            if r["hypothesis_id"] != "H15" or r["evidence_kind"] != KIND[f]:
                raise ValueError(f"hypothesis_id/evidence_kind {r['hypothesis_id']}/{r['evidence_kind']}")
            if "payload" not in r or sha_text(canon(r["payload"])) != r["payload_hash"]:
                raise ValueError("payload_hash does not match the payload")
        except Exception as e:  # noqa: BLE001 - any defect makes the file unusable evidence
            problems.append(f"{f}: unreadable/invalid ({type(e).__name__}: {str(e)[:120]})")
            continue
        recs[f], pay[f] = r, r["payload"]
    return recs, pay, problems


def _g(x, *path, default=None):
    for p in path:
        if not isinstance(x, (dict, list)):
            return default
        try:
            x = x[p]
        except (KeyError, IndexError, TypeError):
            return default
    return x


def evaluate(exp_dir, root: Path = ROOT) -> dict:
    d = Path(exp_dir)
    th = json.loads((root / "protocol/thresholds.json").read_text())["H15"]
    fz = json.loads((root / "protocol/FREEZE.json").read_text())["protocol_sha256"]
    g0 = json.loads((root / "protocol/H15_GATE0.json").read_text())["combined_sha256"]
    cand = json.loads((root / "protocol/H15_CANDIDATE.json").read_text())["combined_sha256"]
    schema = json.loads((root / "schemas/evidence-record.schema.json").read_text())
    recs, pay, problems = _load(d, schema)
    P = lambda f: pay.get(f)  # noqa: E731

    # ---------------------------------------------------------------- protocol validity
    v1 = [f for f, r in recs.items() if (r["protocol_freeze_hash"], r.get("gate0_combined_sha256"),
                                         r.get("candidate_combined_sha256")) != (fz, g0, cand)]
    ident = {(r["git_commit"], r.get("seed"), r.get("input_corpus_hash"), r["experiment_id"]) for r in recs.values()}
    mut = P("mutation-results.json")
    v3 = []
    if mut is not None:
        v3 += [f"control not clean: {s}" for s in SURFACES if not _g(mut, "controls", s, "clean", default=False)
               or not _g(mut, "controls", s, "clean_after_restore", default=False)]
        if not _g(mut, "oracle_known_negatives", "all_detected", default=False):
            v3.append("oracle known-negative missed")
    protocol_valid = not v1 and len(ident) <= 1 and not v3

    # ---------------------------------------------------------------- numbers
    n: dict = {"thresholds": th}
    real = P("real-domain-roundtrip.json")
    if real is not None:
        n["real_domains_present"] = [x for x in REGISTERED_DOMAINS if x in real]
        n["real_openpona_non_equivalent"] = [x for x in REGISTERED_DOMAINS if x in real and not _g(real, x, "openpona", "equivalent", default=False)]
        n["real_openpona_not_encoded_completely"] = [x for x in REGISTERED_DOMAINS if x in real and not _g(real, x, "openpona", "encoded_completely", default=False)]
        n["real_dsl_non_equivalent_baseline"] = [x for x in REGISTERED_DOMAINS if x in real and not _g(real, x, "dsl", "equivalent", default=False)]
    gen = P("generated-roundtrip.json")
    if gen is not None:
        op = _g(gen, "surfaces", "openpona", default={})
        n["generated_valid_cases"] = _g(gen, "valid_cases")
        n["generated_unique_packages"] = _g(gen, "generation", "unique")
        n["openpona_ok"], n["openpona_failed"], n["openpona_unrepresentable"] = (op.get("ok"), op.get("failed"), op.get("unrepresentable"))
        n["openpona_harness_errors"] = len(op.get("harness_errors", []))
        n["dsl_baseline_failed"] = _g(gen, "surfaces", "dsl", "failed")
        tot = [(_g(gen, "surfaces", s, "ok", default=0) + _g(gen, "surfaces", s, "failed", default=0)
                + _g(gen, "surfaces", s, "unrepresentable", default=0)) for s in SURFACES]
        n["generated_total_consistent"] = all(t == _g(gen, "generation", "generated") for t in tot)
    met = P("compiler-diff-metrics.json")
    if met is not None:
        n["new_primitive_tokens_required"] = _g(met, "primitive_tokens", "new_primitive_tokens_required")
        n["gap_constructs"] = _g(met, "gap_constructs", "count")
    side = P("sidecar-audit.json")
    if side is not None:
        n["indispensable_sidecar_count"] = _g(side, "indispensable_sidecar_count")
        n["reference_slots_total_domains"] = {k: _g(v, "reference_slots_total") for k, v in _g(side, "domains", default={}).items()}
        n["reference_slots_via_coreference_labels_domains"] = {k: _g(v, "reference_slots_via_coreference_labels") for k, v in _g(side, "domains", default={}).items()}
    amb = P("ambiguity-corpus.json")
    if amb is not None:
        s = _g(amb, "summary", "openpona", default={})
        n["ambiguity_openpona"] = s
        n["ambiguity_dsl_baseline"] = _g(amb, "summary", "dsl")
        n["ambiguity_classes_declared"] = _g(amb, "declared", "openpona", "classes_declared")
        n["ambiguity_classes_covered"] = _g(amb, "declared", "openpona", "classes_covered")
    if mut is not None:
        n["mutation"] = {s: _g(mut, "summary", s) for s in SURFACES}
        n["mutation_classes_present"] = {s: sorted(m["class"] for m in mut["mutants"] if m["surface"] == s and m["target"]) for s in SURFACES}
        n["mutation_survivors"] = [m["id"] for m in mut["mutants"] if m["target"] and not m["killed"]]
        n["extra_mutation_survivors_info_only"] = [m["id"] for m in mut["mutants"] if not m["target"] and not m["killed"]]

    # ---------------------------------------------------------------- predicates (None = unknown)
    def known(*keys):
        return all(k in n for k in keys)

    r1 = (bool(n["real_openpona_non_equivalent"]) if known("real_openpona_non_equivalent") else None)
    r2 = ((n["openpona_failed"] or 0) + (n["openpona_unrepresentable"] or 0) + n["openpona_harness_errors"] > 0) if known("openpona_failed") else None
    r3 = None
    if known("new_primitive_tokens_required") and known("indispensable_sidecar_count"):
        r3 = (n["new_primitive_tokens_required"] or 0) > 0 or (n["indispensable_sidecar_count"] or 0) > 0
    r4 = None
    if known("ambiguity_openpona") and n["ambiguity_openpona"]:
        a = n["ambiguity_openpona"]
        r4 = a.get("declared_accepted", 1) > 0 or a.get("declared_crashed", 1) > 0 or a.get("deletion_violations", 1) > 0
    s1 = (not n["real_openpona_non_equivalent"] and len(n["real_domains_present"]) == len(REGISTERED_DOMAINS)) if known("real_openpona_non_equivalent") else None
    s2 = (r2 is False and (n["generated_valid_cases"] or 0) >= th["min_generated_valid_cases"]
          and n["generated_total_consistent"]) if known("openpona_failed") else None
    s3 = (n["new_primitive_tokens_required"] == 0) if known("new_primitive_tokens_required") and n["new_primitive_tokens_required"] is not None else None
    s4 = (n["indispensable_sidecar_count"] == 0) if known("indispensable_sidecar_count") else None
    a = n.get("ambiguity_openpona") or {}
    covered = known("ambiguity_classes_declared") and set(n["ambiguity_classes_declared"] or []) == set(n["ambiguity_classes_covered"] or [])
    s5 = (a.get("declared_total", 0) > 0 and a.get("declared_fail_closed") == a.get("declared_total") and a.get("declared_accepted", 1) == 0
          and a.get("declared_crashed", 1) == 0 and a.get("deletion_violations", 1) == 0 and a.get("deletion_total", 0) >= 1000
          and covered) if known("ambiguity_openpona") else None
    s6 = None
    if mut is not None:
        s6 = all((n["mutation"][s] or {}).get("kill_rate", 0) >= th["required_mutation_kill_rate"]
                 and set(TARGET_CLASSES) <= set(n["mutation_classes_present"][s]) for s in SURFACES)
    i1 = ((n["generated_valid_cases"] or 0) < th["min_generated_valid_cases"]) if known("generated_valid_cases") else None
    i2 = (bool(n["real_openpona_not_encoded_completely"]) or len(n["real_domains_present"]) < len(REGISTERED_DOMAINS)) if known("real_openpona_not_encoded_completely") else None

    def rows(table, vals):
        return [{"id": k, "clause": t, "value": vals[k]} for k, t in table.items()]
    pred = {"support_if": rows(SUPPORT, {"S1": s1, "S2": s2, "S3": s3, "S4": s4, "S5": s5, "S6": s6}),
            "reject_if": rows(REJECT, {"R1": r1, "R2": r2, "R3": r3, "R4": r4}),
            "inconclusive_if": rows(INCONCLUSIVE, {"I1": i1, "I2": i2}),
            "invalid_if": rows(INVALID, {"V1": bool(v1), "V2": len(ident) > 1, "V3": bool(v3)})}
    complete = not problems and n.get("generated_total_consistent", False)
    common = CommonEvaluation(
        protocol_valid=protocol_valid, required_evidence_complete=complete,
        sample_sufficient=(i1 is False and i2 is False), reject_hit=any(x is True for x in (r1, r2, r3, r4)),
        support_hit=all(x is True for x in (s1, s2, s3, s4, s5, s6)))
    verdict = evaluate_common(common)
    return {"experiment_id": next(iter(ident))[3] if ident else None, "hypothesis_id": "H15", "verdict": verdict.value,
            "common": {"protocol_valid": common.protocol_valid, "required_evidence_complete": common.required_evidence_complete,
                       "sample_sufficient": common.sample_sufficient, "reject_hit": common.reject_hit,
                       "support_hit": common.support_hit},
            "predicates": pred, "numbers": n, "problems": problems,
            "protocol_mismatches": {"records_with_wrong_hashes": v1, "disagreeing_provenance": len(ident) > 1, "harness_self_check": v3},
            "protocol": {"freeze_sha256": fz, "gate0_combined_sha256": g0, "candidate_combined_sha256": cand},
            "evidence_payload_hashes": {f: r["payload_hash"] for f, r in sorted(recs.items())},
            "evaluator_sha256": sha_file(Path(__file__)),
            "interpretation_notes": [
                "R4 maps falsifier 5 (silent invention of semantics) to reject; the contract's reject_if list names only R1-R3.",
                "Mutation kill rate is judged on target classes for BOTH compilers; extra mutants are informational.",
                "The DSL baseline numbers are reported but only OpenPona enters S1-S5."]}
