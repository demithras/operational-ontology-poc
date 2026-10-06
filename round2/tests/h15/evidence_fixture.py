"""Synthetic H15 evidence directories for the evaluator tests (not a test module)."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from eoo_h15.evaluate import TARGET_CLASSES
from eoo_h15.evidence import REQUIRED, wrap, write

ROOT = Path(__file__).resolve().parents[2]
FZ = json.loads((ROOT / "protocol/FREEZE.json").read_text())["protocol_sha256"]
G0 = json.loads((ROOT / "protocol/H15_GATE0.json").read_text())["combined_sha256"]
CAND = json.loads((ROOT / "protocol/H15_CANDIDATE.json").read_text())["combined_sha256"]
CLASSES = ["missing_type", "missing_cardinality"]
PROV = {"experiment_id": "exp-test", "hypothesis_id": "H15", "git_commit": "c0ffee", "protocol_freeze_hash": FZ,
        "environment": {}, "seed": 15, "input_corpus_hash": "abc", "oracle_version": "o", "variant_versions": {},
        "gate0_combined_sha256": G0, "candidate_combined_sha256": CAND}


def _dom(eq=True, complete=True):
    side = {"equivalent": eq, "encoded_completely": complete}
    return {"resources_total": 5, "openpona": dict(side), "dsl": dict(side)}


def _surf(ok=10000, failed=0, unrep=0):
    return {"ok": ok, "failed": failed, "unrepresentable": unrep, "exact_equal": ok, "mean_render_ms": 1.0, "mean_compile_ms": 2.0}


def _amb(total=44, closed=44, acc=0, crash=0, dtotal=1500, viol=0):
    return {"declared_total": total, "declared_fail_closed": closed, "declared_accepted": acc, "declared_crashed": crash,
            "deletion_total": dtotal, "deletion_violations": viol, "deletion_raised": 1000, "deletion_accepted_exact": 500}


def _mut(surface):
    return {"id": surface, "surface": surface, "class": "x", "target": True, "killed": True}


def positive() -> dict:
    muts = [{"id": f"{s}:{c}", "surface": s, "class": c, "target": True, "killed": True, "hits": {"non_equivalent": 1}}
            for s in ("openpona", "dsl") for c in TARGET_CLASSES]
    return {
        "real-domain-roundtrip.json": {"manufacturing": _dom(), "project": _dom()},
        "generated-roundtrip.json": {"valid_cases": 10000, "generation": {"generated": 10000, "unique": 9000, "corpus_sha256": "abc"},
                                     "surfaces": {"openpona": _surf(), "dsl": _surf()}},
        "ambiguity-corpus.json": {"summary": {"openpona": _amb(), "dsl": _amb(39, 39)},
                                  "declared": {"openpona": {"classes_declared": CLASSES, "classes_covered": CLASSES}}},
        "sidecar-audit.json": {"indispensable_sidecar_count": 0, "domains": {"manufacturing": {"reference_slots_total": 3, "reference_slots_via_coreference_labels": 3}}},
        "mutation-results.json": {"controls": {s: {"clean": True, "clean_after_restore": True} for s in ("openpona", "dsl")},
                                  "oracle_known_negatives": {"all_detected": True}, "mutants": muts,
                                  "summary": {s: {"target_mutants": 6, "killed": 6, "kill_rate": 1.0} for s in ("openpona", "dsl")}},
        "compiler-diff-metrics.json": {"primitive_tokens": {"new_primitive_tokens_required": 0}, "gap_constructs": {"count": 0}},
    }


def build(tmp: Path, mutate=None, prov_for=None, drop=(), tamper=None) -> Path:
    """Write a dir; mutate(payloads) edits payloads; prov_for(filename)->dict overrides provenance fields."""
    pay = copy.deepcopy(positive())
    if mutate:
        mutate(pay)
    tmp.mkdir(parents=True, exist_ok=True)
    for f in REQUIRED:
        if f in drop:
            continue
        prov = {**PROV, **(prov_for(f) if prov_for else {})}
        write(tmp, f, wrap(prov, f, pay[f]))
    if tamper:
        p = tmp / tamper
        r = json.loads(p.read_text())
        r["payload"]["tampered"] = True  # payload_hash no longer matches
        p.write_text(json.dumps(r))
    return tmp
