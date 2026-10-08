"""H25 contract evaluator (hypotheses/h25/contract.json) with protocol/thresholds.json H25 and the frozen floors
(PROT-H25 s7; ORACLE-AND-HARNESS-G3 A6), per variant. Every number is recomputed from the raw rows (analyze.py).

REJECTED (author ruling Q5, any preregistered falsifier): domain_branch, procedural_mismatch / illegitimate_effect /
invalid_doc_accepted / linearizability_violation, fabricated_judgment, emergency_violation, write-ledger violations.
SUPPORTED needs zero of every violation class, procedural equality 1.0, kill rate 1.0 and every floor. INCONCLUSIVE:
< 3 structurally distinct models, a model below its coverage floor, cases below the minimum, progress < 1.0,
unsupported / world_lock_timeout, boundary probes below their minimum. INVALID: a FREEZE_G3 hash differs, the oracle
imports a variant or fixture code, judgment values not from the separate judgment stream, evidence hash mismatch,
required evidence missing. Minimum overrides are stamped and refused on non-dev ids (scripts/evaluate_h25.py)."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

from r3_shared import evidence, mutants
from r3_shared.governance import structurally_distinct
from r3_shared.verdict import CommonEvaluation, DualVerdict, Verdict, evaluate_common

from r3_harness.h23 import comparative

from . import analyze as AN
from .gen_model import fixture
from .rows import EQUALITY, VIOLATIONS

ROUND3 = Path(__file__).resolve().parents[3]
PROT_REL = "spec/protections/PROT-H25.md"
EVAL_FILES = ("evaluator.py", "analyze.py", "rows.py")
BANNED = ("paladin", "conventional", "r3_harness", "eoo_", "tests")
LEDGER = ("unattributed_write", "writer_violation", "unlogged_write")
FLOORS = {"oracle_needed_cases": 1000, "precedence_conflict_cases": 500, "race_cases": 1000, "merit_cases": 1000,
          "flip_changed": 1000, "per_model_cases": 3000}


def evaluator_sha256() -> str:
    h = hashlib.sha256()
    for f in EVAL_FILES:
        h.update(f.encode() + (Path(__file__).parent / f).read_bytes())
    return h.hexdigest()


def oracle_independent() -> tuple[bool, list[str]]:
    bad = []
    for f in sorted((ROUND3 / "src" / "r3_oracle").rglob("*.py")):
        for n in ast.walk(ast.parse(f.read_text())):
            mods = [a.name for a in n.names] if isinstance(n, ast.Import) else (
                [n.module or ""] if isinstance(n, ast.ImportFrom) and n.level == 0 else [])
            for m in mods:
                if m.startswith(BANNED) or m == "r3_shared.variant":
                    bad.append(f"{f.name}: imports {m}")
    return not bad, bad


def freeze_g3() -> dict:
    return json.loads((ROUND3 / "protocol" / "FREEZE_G3.json").read_text())["files"]


def freeze_g3_mismatches() -> list[str]:
    bad = []
    for rel, want in sorted(freeze_g3().items()):
        f = ROUND3 / rel
        got = hashlib.sha256(f.read_bytes()).hexdigest() if f.is_file() else None
        if got != want:
            bad.append(f"{rel}: sha256 {str(got)[:12]} differs from protocol/FREEZE_G3.json {want[:12]}")
    return bad


def minimum_overrides(thresholds: dict, min_cases) -> dict:
    frozen = thresholds["H25"]["min_generated_authority_cases"]
    return {"min_cases": min_cases} if min_cases is not None and min_cases != frozen else {}


def _finish(vname, valid, complete, sample, reject, support, reasons, metrics) -> dict:
    v = evaluate_common(CommonEvaluation(protocol_valid=valid, required_evidence_complete=complete,
                                         sample_sufficient=sample, reject_hit=reject, support_hit=support))
    return {"variant": vname, "verdict": v.value, "reasons": reasons, "metrics": metrics}


def _check_files(vdir: Path, reasons: list[str]) -> tuple[bool, dict | None]:
    missing = [f for f in (*AN.FILES, *AN.EXTRA, "envelope.json") if not (vdir / f).is_file()]
    if missing:
        reasons.append("required evidence missing: " + ", ".join(missing))
        return False, None
    ok, env = True, json.loads((vdir / "envelope.json").read_text())
    try:
        evidence.validate_envelope(env)
        raw = env["raw_observations"]
        for f in AN.FILES + AN.EXTRA:
            if hashlib.sha256((vdir / f).read_bytes()).hexdigest() != raw["evidence_sha256"].get(f):
                ok = False
                reasons.append(f"{f}: sha256 differs from envelope")
        if raw.get("prot_h25_sha256") != freeze_g3()[PROT_REL]:
            ok = False
            reasons.append("PROT-H25.md sha256 in the envelope differs from protocol/FREEZE_G3.json: semantics changed")
        if raw.get("evaluator_sha256") != evaluator_sha256():
            ok = False
            reasons.append("evaluator sha256 differs from the one recorded at run time")
    except Exception as exc:  # noqa: BLE001
        ok = False
        reasons.append(f"envelope invalid: {exc}")
    return ok, env


def _provenance_ok(oba: dict, reasons: list[str]) -> bool:
    p = oba.get("provenance") or {}
    ok = p.get("streams_distinct") is True and bool(p.get("judgment_rng_stream"))
    if not ok:
        reasons.append("judgment values are not from the separate judgment RNG stream (oracle-boundary-audit provenance)")
    for rel, sha in (p.get("fixtures_sha256") or {}).items():
        f = ROUND3 / rel
        if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest() != sha:
            ok = False
            reasons.append(f"governance fixture {rel} changed since the run")
    if p.get("oracle_imports") is None or any(i.split(".")[0] in ("paladin", "conventional", "r3_harness") for i in p["oracle_imports"]):
        ok = False
        reasons.append("oracle imports a variant or harness code")
    return ok


def _models_distinct(models: dict) -> tuple[int, list[str]]:
    names = [m for m in AN.MODELS if models.get(m, {}).get("cases", 0) > 0]
    sigs = {m: AN.signature(m) for m in names}
    best = 0
    for m in names:
        group = [m]
        for o in names:
            if o != m and all(structurally_distinct(sigs[o], sigs[g]) for g in group):
                group.append(o)
        best = max(best, len(group))
    return best, names


def _evaluate_variant(vdir: Path, thresholds: dict, vname: str, min_cases=None) -> dict:
    t = thresholds["H25"]
    need = t["min_generated_authority_cases"] if min_cases is None else min_cases
    scale = need / t["min_generated_authority_cases"]
    fl = {k: max(1, int(v * scale)) for k, v in FLOORS.items()}
    reasons: list[str] = []
    relax = min_cases is not None and min_cases != t["min_generated_authority_cases"]
    ind, bad = oracle_independent()
    valid = ind
    reasons += bad
    drift = freeze_g3_mismatches()
    if drift:
        valid = False
        reasons += ["frozen G3 spec changed: " + d for d in drift]
    files_ok, env = _check_files(vdir, reasons)
    if env is None:
        return _finish(vname, False, False, False, False, False, reasons, {})
    valid = valid and files_ok
    a = AN.analyze(vdir)
    corpus = json.loads((vdir / AN.FILES[0]).read_text())
    diff = json.loads((vdir / AN.FILES[1]).read_text())
    dba = json.loads((vdir / AN.FILES[2]).read_text())
    oba = json.loads((vdir / AN.FILES[3]).read_text())
    mut = json.loads((vdir / AN.FILES[4]).read_text())
    if diff.get("class_counts") != a["class_counts"] or corpus.get("unique_cases") != a["unique_cases"]:
        valid = False
        reasons.append("summary files disagree with the raw rows")
    valid = _provenance_ok(oba, reasons) and valid
    names = mutants.KNOWN["H25"]
    mut_ok = all(n in mut for n in names)
    killed = sum(1 for n in names if mut.get(n, {}).get("killed") is True)
    kill_rate = killed / len(names) if mut_ok else None
    cc = a["class_counts"]
    n = {k: cc.get(k, 0) for k in (*VIOLATIONS, "unsupported", "world_lock_timeout")}
    flip, merit = oba.get("judgment_flip") or {}, oba.get("merit_invariance") or {}
    ren = dba.get("renaming") or {}
    num = lambda d, k: d.get(k) if type(d.get(k)) is int else None  # noqa: E731  None / missing / non-int = missing evidence
    if None in (num(flip, "mismatch"), num(merit, "fabricated"), num(dba, "domain_branch"), num(merit, "cases"),
                num(flip, "oracle_outcome_changed"), num(ren, "cases")):
        reasons.append("boundary / domain-branch evidence incomplete (missing or non-integer keys)")
        flip, merit, ren, dba = ({"mismatch": 0, "oracle_outcome_changed": 0}, {"fabricated": 0, "cases": 0},
                                 {"cases": 0}, {"domain_branch": 0})
        evidence_gap = True
    else:
        evidence_gap = False
    n["procedural_mismatch"] += flip["mismatch"]
    n["progress_loss"] += flip.get("progress_loss") or 0
    n["fabricated_judgment"] += merit["fabricated"]
    n["domain_branch"] += dba["domain_branch"]
    equality = (1 - sum(n[k] for k in EQUALITY) / a["actions"]) if a["actions"] else None
    short = []
    if a["unique_cases"] < need:
        short.append(f"unique cases {a['unique_cases']} < {need}")
    distinct, exercised = _models_distinct(a["models"])
    if distinct < t["min_governance_models"]:
        short.append(f"{distinct} structurally distinct governance models exercised < {t['min_governance_models']}")
    for m, v in a["models"].items():
        r = v["reachable"]
        if v["cases"] < fl["per_model_cases"]:
            short.append(f"model {m}: {v['cases']} cases < {fl['per_model_cases']}")
        if len(v["domains"]) != 2:
            short.append(f"model {m}: exercised on {v['domains']} (both domains required)")
        lost = sorted(set(r["rules"]) - set(v["rules"]))
        lost_r = sorted(set(r["reasons"]) - set(v["reasons"]))
        if relax:  # DEV ONLY (stamped): decision rule + 50% of the reachable refusal classes
            lost = [] if "decision" in v["rules"] else lost
            lost_r = lost_r if len(lost_r) > len(r["reasons"]) // 2 else []
        if lost or lost_r:
            short.append(f"model {m}: uncovered outcome rules {lost} refusal classes {lost_r}")
    for key in ("oracle_needed_cases", "precedence_conflict_cases", "race_cases"):
        if a[key] < fl[key]:
            short.append(f"{key} {a[key]} < {fl[key]} (PROT-H25 s7 / A2)")
    if a["progress"]["ratio"] is None or a["progress"]["ratio"] < 1.0:
        short.append(f"legit progress {a['progress']['ratio']} < 1.0")
    if merit["cases"] < fl["merit_cases"] or flip["oracle_outcome_changed"] < fl["flip_changed"]:
        short.append(f"boundary probes below minimum (merit {merit['cases']}, flips {flip['oracle_outcome_changed']})")
    if ren["cases"] < fl["merit_cases"]:
        short.append(f"renaming audit sampled {ren['cases']} cases < {fl['merit_cases']}")
    if n["unsupported"] or n["world_lock_timeout"]:
        short.append(f"unsupported={n['unsupported']} world_lock_timeout={n['world_lock_timeout']}: unmeasurable is not safe")
    reasons += short
    forbidden = ("domain_branch", "procedural_mismatch", "illegitimate_effect", "invalid_doc_accepted",
                 "linearizability_violation", "fabricated_judgment", "emergency_violation", *LEDGER)
    reject = any(n[k] > 0 for k in forbidden)
    others = sum(n[k] for k in VIOLATIONS)
    support = (not evidence_gap and others == 0 and equality == 1.0 and kill_rate is not None and kill_rate >= t["required_mutation_kill_rate"])
    if reject:
        reasons.append("reject: " + ", ".join(f"{k}={n[k]}" for k in forbidden if n[k]))
    elif not support:
        reasons.append(f"support conditions unmet: violations={ {k: n[k] for k in VIOLATIONS if n[k]} } "
                       f"equality={equality} kill_rate={kill_rate}")
    metrics = {"forbidden_effects": n["illegitimate_effect"], "procedural_equality": equality,
               "domain_branches": n["domain_branch"], "fabricated_judgments": n["fabricated_judgment"],
               "emergency_violations": n["emergency_violation"], "mutation_kill_rate": kill_rate,
               "safe_progress_ratio": a["progress"]["ratio"], "p50_latency_ms": a["latency_ms"]["p50"],
               "p95_latency_ms": a["latency_ms"]["p95"], "unique_cases": a["unique_cases"], "distinct_models": distinct,
               "loc": comparative.security_specific_loc(vname), "class_counts": cc, "violations": {k: n[k] for k in VIOLATIONS},
               "payload_sha256": env.get("payload_sha256"), "evidence_sha256": env["raw_observations"]["evidence_sha256"]}
    return _finish(vname, valid, mut_ok and a["cases"] > 0 and not evidence_gap, not short, reject, support, reasons, metrics)


def evaluate_variant(vdir: Path, thresholds: dict, vname: str, min_cases=None) -> dict:
    res = _evaluate_variant(vdir, thresholds, vname, min_cases)
    ov = minimum_overrides(thresholds, min_cases)
    res["minimum_overrides"] = ov
    res["reasons"] = list(res["reasons"]) + [f"DEV ONLY: minimum {k} overridden to {v} (all volume floors scaled; coverage floors "
                                             f"relaxed to the decision rule + 50% of reachable refusal classes)" for k, v in ov.items()]
    return res


def evaluate_experiment(exp_dir: Path, thresholds: dict, min_cases=None) -> dict:
    vs = {d.name: evaluate_variant(d, thresholds, d.name, min_cases) for d in sorted(p for p in exp_dir.iterdir() if p.is_dir())}
    comp = {"forbidden_effects": {n: v["metrics"].get("forbidden_effects") for n, v in vs.items()},
            "safe_progress_ratio": {n: v["metrics"].get("safe_progress_ratio") for n, v in vs.items()},
            "mutation_kill_rate": {n: v["metrics"].get("mutation_kill_rate") for n, v in vs.items()},
            "p95_latency_ms": {n: v["metrics"].get("p95_latency_ms") for n, v in vs.items()},
            "security_specific_loc": {n: comparative.security_specific_loc(n) for n in vs},
            "security_specific_components": {n: comparative.security_specific_components(n) for n in vs}}
    pick = lambda n: Verdict(vs[n]["verdict"]) if n in vs else None  # noqa: E731
    out = DualVerdict(pick("paladin"), pick("conventional"), comp).to_json()
    out.update({"experiment_id": exp_dir.name, "hypothesis": "H25", "evaluator_sha256": evaluator_sha256(),
                "thresholds_sha256": evidence.sha256_of(thresholds["H25"]),
                "minimum_overrides": minimum_overrides(thresholds, min_cases), "variants": vs})
    return out


_ = fixture
