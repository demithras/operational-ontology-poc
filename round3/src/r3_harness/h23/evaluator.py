"""H23 contract evaluator (hypotheses/h23/contract.json) with protocol/thresholds.json, per variant.

Everything is recomputed from the raw adversarial-sequences.jsonl; summary files are only cross-checked.
INVALID: oracle/meter import candidate code or trust CallResult, envelope/hash mismatch, required evidence missing.
INCONCLUSIVE: too few unique sequences, A1/A2/A8 not all covered, either domain or any operation uncovered,
mutation proof incomplete. REJECTED: any forbidden effect / identity expansion / backstop failure.
SUPPORTED additionally needs 100% safe progress and 100% mutation kills.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

from r3_shared import evidence, mutants
from r3_shared.verdict import CommonEvaluation, Verdict, evaluate_common

from . import concurrency, crash_rules
from .analyze import analyze
from .runner import A8_FILES, FILES, ROUND3

EVAL_FILES = ("evaluator.py", "analyze.py", "corpus.py", "classify.py", "concurrency.py", "crash_rules.py")
MIN_CONCURRENCY = 300  # PROT-H23-A8 official configuration; lowered only via the evaluate_* parameter in tests
BANNED_IMPORTS = ("paladin", "conventional", "r3_harness", "eoo_")


def evaluator_sha256() -> str:
    h = hashlib.sha256()
    for f in EVAL_FILES:
        h.update(f.encode() + (Path(__file__).parent / f).read_bytes())
    return h.hexdigest()


def oracle_independent() -> tuple[bool, list[str]]:
    bad = []
    for f in sorted((ROUND3 / "src" / "r3_oracle").rglob("*.py")):
        tree = ast.parse(f.read_text())
        for n in ast.walk(tree):
            mods = [a.name for a in n.names] if isinstance(n, ast.Import) else (
                [n.module or ""] if isinstance(n, ast.ImportFrom) and n.level == 0 else [])
            for m in mods:
                if m.startswith(BANNED_IMPORTS) or m == "r3_shared.variant":
                    bad.append(f"{f.name}: imports {m}")
            if f.name == "effect_meter.py" and isinstance(n, ast.Attribute) and n.attr in ("status", "body"):
                bad.append(f"{f.name}: reads CallResult.{n.attr}")
    return not bad, bad


def count_loc(variant: str) -> dict | None:
    root = ROUND3 / "src" / variant
    if not root.is_dir():
        return None
    vend = {}
    vf = root / "VENDORED.json"
    if vf.exists():
        def walk(x, acc):
            if isinstance(x, dict):
                for k, v in x.items():
                    if isinstance(v, str) and len(v) == 64:
                        acc[Path(k).name] = v
                    walk(v, acc)
            elif isinstance(x, list):
                for i in x:
                    walk(i, acc)
        walk(json.loads(vf.read_text()), vend)
    total = excl = 0
    comps = []
    for f in sorted(root.rglob("*.py")):
        n = sum(1 for ln in f.read_text().splitlines() if ln.strip() and not ln.strip().startswith("#"))
        total += n
        if vend.get(f.name) == hashlib.sha256(f.read_bytes()).hexdigest():
            excl += n
        else:
            comps.append({"file": f.relative_to(root).as_posix(), "loc": n})
    return {"total_loc": total, "vendored_unchanged_loc": excl, "security_specific_loc": total - excl,
            "components": comps}


def _read(p: Path):
    return json.loads(p.read_text())


def evaluate_variant(vdir: Path, thresholds: dict, vname: str, min_sequences: int | None = None,
                     min_concurrency: int | None = None) -> dict:
    t = thresholds["H23"]
    need = t["min_adversarial_sequences"] if min_sequences is None else min_sequences
    reasons: list[str] = []
    valid = True
    ok_ind, bad = oracle_independent()
    if not ok_ind:
        valid, reasons = False, reasons + bad
    missing = [f for f in (*FILES, "envelope.json") if not (vdir / f).is_file()]
    if missing:
        return _finish(vname, False, False, False, False, False, ["required evidence missing: " + ", ".join(missing)], {})
    env = _read(vdir / "envelope.json")
    try:
        evidence.validate_envelope(env)
        hashes = env["raw_observations"]["evidence_sha256"]
        for f in FILES + tuple(f for f in A8_FILES if (vdir / f).is_file()):
            if hashlib.sha256((vdir / f).read_bytes()).hexdigest() != hashes.get(f):
                valid = False
                reasons.append(f"{f}: sha256 differs from envelope")
    except Exception as exc:  # noqa: BLE001
        valid = False
        reasons.append(f"envelope invalid: {exc}")
    a = analyze(vdir / FILES[0])
    summ = _read(vdir / FILES[1])
    if summ.get("class_counts") != a["class_counts"] or summ.get("unique_sequences") != a["unique_sequences"]:
        valid = False
        reasons.append("effect-oracle-diff.json disagrees with the raw sequences")
    if a["oracle_errors"]:
        valid = False
        reasons.append(f"the oracle failed on {a['oracle_errors']} calls")
    mut = _read(vdir / FILES[4])
    surf = _read(vdir / FILES[5])
    names = mutants.KNOWN["H23"]
    mut_ok = all(n in mut for n in names)
    killed = sum(1 for n in names if mut.get(n, {}).get("killed") is True)
    kill_rate = killed / len(names) if mut_ok else None
    cc = a["class_counts"]
    conc, a8_reasons = _a8(vdir, a, MIN_CONCURRENCY if min_concurrency is None else min_concurrency)
    forb = cc.get("forbidden_effect", 0) + a["a8_only_safety"] + conc["summary"]["concurrency_unserializable"]
    ident, bsf = a["identity_expansions"], cc.get("backstop_failure", 0)
    ops_total = {f"{d}:{o['name']}" for d in a["domains"] for o in _ops(d)}
    covered = all(a["op_coverage"].get(k, 0) > 0 for k in ops_total) and len(a["domains"]) == 2
    a_ok = all(a["a_class_calls"].get(c, 0) > 0 for c in ("A1", "A2", "A8"))
    a_ok = a_ok and not a8_reasons
    sample = a["unique_sequences"] >= need and a_ok and covered
    reasons += a8_reasons
    if a["unique_sequences"] < need:
        reasons.append(f"unique sequences {a['unique_sequences']} < {need}")
    if not a_ok:
        reasons.append("attack coverage omits A1/A2/A8")
    if not covered:
        reasons.append("an operation or domain is not covered")
    reject = (forb > t["max_forbidden_effects"] or ident > t["max_identity_confusions"]
              or bsf > 0 or (a["backstop_rate"] is not None and a["backstop_rate"] < t["required_direct_engine_backstop"]))
    support = (forb == 0 and ident == 0 and bsf == 0 and a["backstop_tested"] > 0
               and a["backstop_rate"] == t["required_direct_engine_backstop"]
               and a["safe_progress_ratio"] == 1.0 and kill_rate is not None
               and kill_rate >= t["required_mutation_kill_rate"])
    if reject:
        reasons.append(f"forbidden={forb} identity_expansions={ident} backstop_failures={bsf}")
    if not support and not reject:
        reasons.append(f"support conditions unmet: progress={a['safe_progress_ratio']} kill_rate={kill_rate} "
                       f"backstop_tested={a['backstop_tested']}")
    metrics = {"forbidden_effects": forb, "identity_expansions": ident, "backstop_failures": bsf,
               "backstop_rate": a["backstop_rate"], "safe_progress_ratio": a["safe_progress_ratio"],
               "mutation_kill_rate": kill_rate, "p50_latency_ms": a["legit_latency_ms"]["p50"],
               "p95_latency_ms": a["legit_latency_ms"]["p95"], "unique_sequences": a["unique_sequences"],
               "surface_overexposure": surf["overexposure"],
               "crash_duplicate_effects": cc.get("crash_duplicate_effect", 0),
               "crash_state_mismatches": cc.get("crash_state_mismatch", 0),
               "concurrency_unserializable": conc["summary"]["concurrency_unserializable"],
               "concurrent_progress_loss": conc["summary"]["concurrent_progress_loss"],
               "concurrency_scenarios": conc["summary"]["executed"], "concurrency_summary": conc["summary"],
               "crash_labels": a["crash"], "loc": count_loc(vname),
               "payload_sha256": env.get("payload_sha256"), "evidence_sha256": env["raw_observations"].get("evidence_sha256")}
    complete = mut_ok and a["calls"] > 0
    return _finish(vname, valid, complete, sample, reject, support, reasons, metrics)


def _a8(vdir: Path, a: dict, need_conc: int) -> tuple[dict, list[str]]:
    """PROT-H23-A8 coverage, recomputed from raw rows. Anything missing -> reasons (the caller makes it INCONCLUSIVE)."""
    why: list[str] = []
    rows, summ = [], concurrency.summarise([])
    cf = vdir / A8_FILES[1]
    if not cf.is_file():
        why.append("attack coverage omits A8: concurrency-results.json missing")
    else:
        rows = json.loads(cf.read_text()).get("scenarios") or []
        summ = concurrency.summarise(rows)
        if not rows:
            why.append("attack coverage omits A8: concurrency-results.json is empty")
        else:
            if summ["executed"] < need_conc:
                why.append(f"concurrency scenarios executed {summ['executed']} < {need_conc}")
            miss = [t for t in concurrency.TYPES if not summ["by_type"].get(t)]
            miss += [f"same k={k}" for k in map(str, concurrency.KS) if not summ["same_k"].get(k)]
            if miss:
                why.append("concurrency scenario types not exercised: " + ", ".join(miss))
    if not (vdir / A8_FILES[0]).is_file():
        why.append("attack coverage omits A8: crash-results.json missing")
    else:
        if a["class_counts"].get("crash_unsupported"):
            why.append("arm_crash/crash/restart not implemented by the variant (crash_unsupported)")
        lab = a["crash"]
        miss = [r for r in crash_rules.REQUIRED if not lab.get(r, {}).get("calls")
                or (r.endswith(":armed") and not lab[r].get("triggered"))]
        if miss:
            why.append("crash scenarios not exercised: " + ", ".join(miss))
    return {"summary": summ, "rows": len(rows)}, why


def _ops(domain: str):
    from r3_shared.opsspec import load_ops_spec
    return load_ops_spec(domain)["operations"]


def _finish(vname, valid, complete, sample, reject, support, reasons, metrics) -> dict:
    v = evaluate_common(CommonEvaluation(protocol_valid=valid, required_evidence_complete=complete,
                                         sample_sufficient=sample, reject_hit=reject, support_hit=support))
    return {"variant": vname, "verdict": v.value, "reasons": reasons, "metrics": metrics}


def evaluate_experiment(exp_dir: Path, thresholds: dict, min_sequences: int | None = None,
                        min_concurrency: int | None = None) -> dict:
    vs = {d.name: evaluate_variant(d, thresholds, d.name, min_sequences, min_concurrency)
          for d in sorted(p for p in exp_dir.iterdir() if p.is_dir())}
    from r3_shared.verdict import DualVerdict
    comp = {}
    for fld, key in (("forbidden_effects", "forbidden_effects"), ("safe_progress_ratio", "safe_progress_ratio"),
                     ("mutation_kill_rate", "mutation_kill_rate"), ("p95_latency_ms", "p95_latency_ms"),
                     ("concurrent_progress_loss", "concurrent_progress_loss")):
        comp[fld] = {n: v["metrics"].get(key) for n, v in vs.items()}
    comp["security_specific_loc"] = {n: (v["metrics"].get("loc") or {}).get("security_specific_loc")
                                     for n, v in vs.items()}
    comp["security_specific_components"] = {n: [c["file"] for c in (v["metrics"].get("loc") or {}).get("components", [])]
                                            for n, v in vs.items()}
    pick = lambda n: Verdict(vs[n]["verdict"]) if n in vs else None  # noqa: E731
    out = DualVerdict(pick("paladin"), pick("conventional"), comp).to_json()
    out.update({"experiment_id": exp_dir.name, "hypothesis": "H23", "evaluator_sha256": evaluator_sha256(),
                "thresholds_sha256": evidence.sha256_of(thresholds["H23"]), "variants": vs})
    return out
