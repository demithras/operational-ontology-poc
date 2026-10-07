"""H24 contract evaluator (hypotheses/h24/contract.json) with protocol/thresholds.json H24 and the frozen progress floors
(PROT-H24 s8; OPEN-QUESTIONS Q2/Q3/Q4), per variant. Every number is recomputed from the raw rows (analyze.py).

REJECTED (Q3, any preregistered falsifier): scope_amplification, post_boundary/forbidden/unattributed/writer/unlogged
effects, cycle_grant, linearizability_violation. SUPPORTED needs zero of EVERY violation class (incl. authority_ack_without_
commit, historical_mismatch, progress_loss), 100% race equality, kill rate 1.0 and all floors; anything else short of a
reject is INCONCLUSIVE. INVALID: oracle imports a variant or reads a clock, evidence/envelope hash mismatch, required
evidence missing, PROT-H24.md changed since the run. Minimum overrides are stamped and refused on non-dev ids."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

from r3_shared import evidence, mutants
from r3_shared.verdict import CommonEvaluation, DualVerdict, Verdict, evaluate_common

from r3_harness.h23 import comparative

from .analyze import EXTRA, FILES, TYPES, analyze
from .rows import VIOLATIONS

ROUND3 = Path(__file__).resolve().parents[3]
PROT = ROUND3 / "spec" / "protections" / "PROT-H24.md"
EVAL_FILES = ("evaluator.py", "analyze.py", "rows.py")
BANNED = ("paladin", "conventional", "r3_harness", "eoo_")
CLOCKS = ("time", "datetime")
STALE = ("post_boundary_effect", "forbidden_effect", "unattributed_write", "writer_violation", "unlogged_write")
FLOOR_OVERLAP, FLOOR_PROGRESS, FLOOR_EFFECT_FIRST = 0.50, 1.0, 1  # PROT-H24 s8 (frozen)


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
                if f.name in ("authority_v2.py", "scope_v2.py") and m.split(".")[0] in CLOCKS:
                    bad.append(f"{f.name}: imports {m} (no wall clock in the reference authority)")
    return not bad, bad


def frozen_prot_hash() -> tuple[str, str]:
    """(sha256, source). A FREEZE amendment hash wins; with none recorded the on-disk file is the reference."""
    fz = json.loads((ROUND3 / "protocol" / "FREEZE.json").read_text())
    am = (fz.get("amendments") or {}).get("PROT-H24.md")
    return (am, "protocol/FREEZE.json amendment") if am else (hashlib.sha256(PROT.read_bytes()).hexdigest(), "on-disk file")


def minimum_overrides(thresholds: dict, min_sequences, min_concurrent) -> dict:
    t = thresholds["H24"]
    frozen = {"min_sequences": t["min_authority_sequences"], "min_concurrent": t["min_concurrent_revocation_cases"]}
    given = {"min_sequences": min_sequences, "min_concurrent": min_concurrent}
    return {k: v for k, v in given.items() if v is not None and v != frozen[k]}


def _finish(vname, valid, complete, sample, reject, support, reasons, metrics) -> dict:
    v = evaluate_common(CommonEvaluation(protocol_valid=valid, required_evidence_complete=complete,
                                         sample_sufficient=sample, reject_hit=reject, support_hit=support))
    return {"variant": vname, "verdict": v.value, "reasons": reasons, "metrics": metrics}


def _check_files(vdir: Path, reasons: list[str]) -> tuple[bool, dict | None]:
    missing = [f for f in (*FILES, *EXTRA, "envelope.json") if not (vdir / f).is_file()]
    if missing:
        reasons.append("required evidence missing: " + ", ".join(missing))
        return False, None
    ok, env = True, json.loads((vdir / "envelope.json").read_text())
    try:
        evidence.validate_envelope(env)
        raw = env["raw_observations"]
        for f in FILES + EXTRA:
            if hashlib.sha256((vdir / f).read_bytes()).hexdigest() != raw["evidence_sha256"].get(f):
                ok = False
                reasons.append(f"{f}: sha256 differs from envelope")
        want, src = frozen_prot_hash()
        if raw.get("prot_h24_sha256") != want:
            ok = False
            reasons.append(f"PROT-H24.md sha256 in the envelope differs from the frozen one ({src}): semantics changed")
        if raw.get("evaluator_sha256") != evaluator_sha256():
            ok = False
            reasons.append("evaluator sha256 differs from the one recorded at run time")
    except Exception as exc:  # noqa: BLE001
        ok = False
        reasons.append(f"envelope invalid: {exc}")
    return ok, env


def _evaluate_variant(vdir: Path, thresholds: dict, vname: str, min_sequences=None, min_concurrent=None) -> dict:
    t = thresholds["H24"]
    need_seq = t["min_authority_sequences"] if min_sequences is None else min_sequences
    need_conc = t["min_concurrent_revocation_cases"] if min_concurrent is None else min_concurrent
    reasons: list[str] = []
    ind, bad = oracle_independent()
    valid = ind
    reasons += bad
    files_ok, env = _check_files(vdir, reasons)
    if env is None:
        return _finish(vname, False, False, False, False, False, reasons, {})
    valid = valid and files_ok
    a = analyze(vdir)
    summ = json.loads((vdir / FILES[0]).read_text())
    if summ.get("class_counts") != a["class_counts"] or summ.get("unique_sequences") != a["unique_sequences"]:
        valid = False
        reasons.append("authority-state-machine.json disagrees with the raw rows")
    mut = json.loads((vdir / FILES[4]).read_text())
    names = mutants.KNOWN["H24"]
    mut_ok = all(n in mut for n in names)
    killed = sum(1 for n in names if mut.get(n, {}).get("killed") is True)
    kill_rate = killed / len(names) if mut_ok else None
    cc, rc, prog = a["class_counts"], a["races"], a["progress"]
    n = {k: cc.get(k, 0) for k in (*VIOLATIONS, "unsupported", "world_lock_timeout")}
    stale = sum(n[k] for k in STALE)
    equality = (rc["matched"] / rc["executed"]) if rc["executed"] else None
    short = []
    if a["unique_sequences"] < need_seq:
        short.append(f"unique sequences {a['unique_sequences']} < {need_seq}")
    if a["max_depth"] < t["min_delegation_depth"] or not a["sequences_with_depth_ge4"]:
        short.append(f"no committed delegation of depth >= {t['min_delegation_depth']} (max {a['max_depth']})")
    miss = [x for x in TYPES if not rc["by_type"].get(x)]
    if miss:
        short.append("race types not exercised: " + ", ".join(miss))
    if rc["executed"] < need_conc or rc["overlapping"] < need_conc:
        short.append(f"concurrent cases executed {rc['executed']} / overlapping {rc['overlapping']} < {need_conc}")
    if rc["overlap_fraction"] is None or rc["overlap_fraction"] < FLOOR_OVERLAP:
        short.append(f"race overlap fraction {rc['overlap_fraction']} < {FLOOR_OVERLAP}: races may be prevented by the harness")
    if rc["rv_effect_first"] < FLOOR_EFFECT_FIRST:
        short.append("no effect-first order among overlapping RV cases")
    if prog["ratio"] is None or prog["ratio"] < FLOOR_PROGRESS:
        short.append(f"unaffected-legit progress {prog['ratio']} < {FLOOR_PROGRESS}")
    ops = {f"{d}:{o['name']}" for d in a["domains"] for o in _ops(d)}
    if len(a["domains"]) != 2 or not all(a["op_coverage"].get(k) for k in ops):
        short.append("a domain or operation is not covered")
    if n["unsupported"] or n["world_lock_timeout"]:
        short.append(f"unsupported={n['unsupported']} world_lock_timeout={n['world_lock_timeout']}: unmeasurable is not safe")
    reasons += short
    reject = (n["scope_amplification"] > t["max_scope_amplifications"] or stale > t["max_post_revocation_forbidden_effects"]
              or n["cycle_grant"] > 0 or n["linearizability_violation"] > 0)
    others = sum(n[k] for k in VIOLATIONS)
    support = (others == 0 and equality is not None and equality >= t["required_oracle_equality"]
               and kill_rate is not None and kill_rate >= t["required_mutation_kill_rate"])
    if reject:
        falsifiers = ("scope_amplification", "cycle_grant", "linearizability_violation", *STALE)
        reasons.append("reject: " + ", ".join(f"{k}={n[k]}" for k in falsifiers if n[k]))
    elif not support:
        reasons.append(f"support conditions unmet: violations={ {k: n[k] for k in VIOLATIONS if n[k]} } "
                       f"equality={equality} kill_rate={kill_rate}")
    metrics = {"scope_amplifications": n["scope_amplification"], "stale_or_forbidden_effects": stale,
               "cycle_grants": n["cycle_grant"], "linearizability_violations": n["linearizability_violation"],
               "other_violations": {k: n[k] for k in VIOLATIONS if k not in ("scope_amplification", "cycle_grant",
                                                                             "linearizability_violation", *STALE)},
               "race_equality": equality, "mutation_kill_rate": kill_rate, "safe_progress_ratio": prog["ratio"],
               "p50_latency_ms": a["latency_ms"]["p50"], "p95_latency_ms": a["latency_ms"]["p95"],
               "unique_sequences": a["unique_sequences"], "races": rc, "max_depth": a["max_depth"],
               "loc": comparative.security_specific_loc(vname), "class_counts": cc,
               "payload_sha256": env.get("payload_sha256"), "evidence_sha256": env["raw_observations"]["evidence_sha256"]}
    return _finish(vname, valid, mut_ok and a["sequences"] > 0, not short, reject, support, reasons, metrics)


def _ops(domain: str):
    from r3_shared.opsspec import load_ops_spec
    return load_ops_spec(domain)["operations"]


def evaluate_variant(vdir: Path, thresholds: dict, vname: str, min_sequences=None, min_concurrent=None) -> dict:
    res = _evaluate_variant(vdir, thresholds, vname, min_sequences, min_concurrent)
    ov = minimum_overrides(thresholds, min_sequences, min_concurrent)
    res["minimum_overrides"] = ov
    res["reasons"] = list(res["reasons"]) + [f"DEV ONLY: minimum {k} overridden to {v}" for k, v in ov.items()]
    return res


def evaluate_experiment(exp_dir: Path, thresholds: dict, min_sequences=None, min_concurrent=None) -> dict:
    vs = {d.name: evaluate_variant(d, thresholds, d.name, min_sequences, min_concurrent)
          for d in sorted(p for p in exp_dir.iterdir() if p.is_dir())}
    comp = {"forbidden_effects": {n: v["metrics"].get("stale_or_forbidden_effects") for n, v in vs.items()},
            "safe_progress_ratio": {n: v["metrics"].get("safe_progress_ratio") for n, v in vs.items()},
            "mutation_kill_rate": {n: v["metrics"].get("mutation_kill_rate") for n, v in vs.items()},
            "p95_latency_ms": {n: v["metrics"].get("p95_latency_ms") for n, v in vs.items()},
            "security_specific_loc": {n: comparative.security_specific_loc(n) for n in vs},
            "security_specific_components": {n: comparative.security_specific_components(n) for n in vs}}
    pick = lambda n: Verdict(vs[n]["verdict"]) if n in vs else None  # noqa: E731
    out = DualVerdict(pick("paladin"), pick("conventional"), comp).to_json()
    out.update({"experiment_id": exp_dir.name, "hypothesis": "H24", "evaluator_sha256": evaluator_sha256(),
                "thresholds_sha256": evidence.sha256_of(thresholds["H24"]),
                "minimum_overrides": minimum_overrides(thresholds, min_sequences, min_concurrent), "variants": vs})
    return out
