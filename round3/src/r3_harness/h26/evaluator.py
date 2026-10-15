"""H26 contract evaluator (hypotheses/h26/contract.json) with protocol/thresholds.json H26, per variant.
Clauses = ORACLE-AND-HARNESS-G3 B6 + PROT-H26 s9 floors. Everything is recomputed from the raw rows; summaries are only
cross-checked. Missing evidence can never become SUPPORTED."""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

from r3_shared import evidence, mutants
from r3_shared.verdict import CommonEvaluation, DualVerdict, Verdict, evaluate_common

from r3_harness.h23.comparative import security_specific_components, security_specific_loc
from r3_harness.h23.evaluator import oracle_independent

from . import analyze as an

ROUND3 = Path(__file__).resolve().parents[3]
FILES = ("noninterference-pairs.json", "exfiltration-fuzz.json", "tool-schema-disclosure.json",
         "provenance-redaction.json", "mutation-results.json", "safe-progress.json")
EVAL_FILES = ("evaluator.py", "analyze.py", "runner.py", "observe.py", "judge.py", "gen_pair.py", "gen_vary.py",
              "gen_plan.py", "gen_auth.py", "fuzz.py", "mutation.py", "env.py", "sim.py")
# design numbers (PROT-H26 s9 / ruling Q6), not in thresholds.json
FLOORS = {"min_pairs": None, "min_per_kind": 300, "min_per_channel": 500, "min_probes": 1000, "min_aa": 500,
          "min_fuzz_calls": 20000, "max_d4_replaced": 0.5}
LEAK_CLASSES = ("existence_leak", "value_exfiltration", "provenance_overdisclosure")


def evaluator_sha256() -> str:
    h = hashlib.sha256()
    for f in EVAL_FILES:
        h.update(f.encode() + (Path(__file__).parent / f).read_bytes())
    return h.hexdigest()


def _read(p: Path):
    return json.loads(p.read_text())


def frozen_mismatches(dev: bool) -> list[str]:
    """FREEZE_G3 checks. lowproj.py is required in the freeze (contract invalid_if); absent -> only dev ids may proceed."""
    files = _read(ROUND3 / "protocol" / "FREEZE_G3.json")["files"]
    bad = []
    for rel, want in sorted(files.items()):
        f = ROUND3 / rel
        got = hashlib.sha256(f.read_bytes()).hexdigest() if f.is_file() else None
        if got != want:
            bad.append(f"{rel}: sha256 {str(got)[:12]} differs from protocol/FREEZE_G3.json {want[:12]}")
    if "src/r3_oracle/lowproj.py" not in files and not dev:
        bad.append("src/r3_oracle/lowproj.py is not in protocol/FREEZE_G3.json (candidate-independent canonicalisation unfrozen)")
    return bad


def overrides_recorded(ov: dict | None) -> dict:
    return {k: v for k, v in (ov or {}).items() if v is not None and v != FLOORS.get(k)}


def _evaluate_variant(vdir: Path, thresholds: dict, vname: str, dev: bool, ov: dict) -> dict:
    t = thresholds["H26"]
    fl = {**FLOORS, "min_pairs": t["min_noninterference_pairs"], **ov}
    reasons: list[str] = []
    valid = True
    ok_ind, bad = oracle_independent()
    if not ok_ind:
        valid, reasons = False, reasons + bad
    drift = frozen_mismatches(dev)
    if drift:
        valid = False
        reasons += ["frozen G3 spec changed: " + d for d in drift]
    missing = [f for f in (*FILES, "envelope.json", "noninterference-pairs.jsonl.gz") if not (vdir / f).is_file()]
    if missing:
        return _finish(vname, valid, False, False, False, False, reasons + ["required evidence missing: " + ", ".join(missing)], {})
    env = _read(vdir / "envelope.json")
    try:
        evidence.validate_envelope(env)
        ro = env["raw_observations"]
        for f in (*FILES, "noninterference-pairs.jsonl.gz"):
            if hashlib.sha256((vdir / f).read_bytes()).hexdigest() != ro["evidence_sha256"].get(f):
                valid = False
                reasons.append(f"{f}: sha256 differs from envelope")
        files = _read(ROUND3 / "protocol" / "FREEZE_G3.json")["files"]
        if ro.get("prot_h26_sha256") != files["spec/protections/PROT-H26.md"]:
            valid = False
            reasons.append("PROT-H26.md sha256 in the envelope differs from protocol/FREEZE_G3.json")
        low = hashlib.sha256((ROUND3 / "src/r3_oracle/lowproj.py").read_bytes()).hexdigest()
        if ro.get("lowproj_sha256") != low or files.get("src/r3_oracle/lowproj.py", low) != low:
            valid = False
            reasons.append("lowproj.py sha256 differs from the envelope/freeze")
    except Exception as exc:  # noqa: BLE001
        valid = False
        reasons.append(f"envelope invalid: {exc}")
    pairs = _read(vdir / FILES[0])
    with gzip.open(vdir / "noninterference-pairs.jsonl.gz", "rt") as fh:
        rows = [json.loads(x) for x in fh]
    if hashlib.sha256((vdir / "noninterference-pairs.jsonl.gz").read_bytes()).hexdigest() != pairs.get("pairs_sha256"):
        valid = False
        reasons.append("pairs file hash differs from noninterference-pairs.json")
    ag = an.aggregate(rows)  # recomputed from raw rows
    c = ag["counts"]
    fz = _read(vdir / FILES[1])
    sp = _read(vdir / FILES[5])
    mut = _read(vdir / FILES[4])
    names = mutants.KNOWN["H26"]
    mm = mut.get("mutants", {})
    mut_ok = all(n in mm for n in names)
    killed = sum(1 for n in names if mm.get(n, {}).get("killed") is True)
    kill_rate = killed / len(names) if mut_ok else None
    div = sum(v for k, v in c.items() if k.startswith("divergence:"))
    leaks = {"divergence": div, "existence_leak": len(fz.get("existence_leak", [])),
             "value_exfiltration": c.get("value_exfiltration", 0) + len(fz.get("value_exfiltration", [])),
             "provenance_overdisclosure": c.get("provenance_overdisclosure", 0)}
    hidden_cap = c.get("hidden_capability", 0) + c.get("schema_disclosure", 0)
    false_prov = c.get("false_provenance", 0)
    unsupported = c.get("label:unsupported", 0) + fz.get("unsupported", 0)
    broken = c.get("label:variant_error", 0) + fz.get("variant_error", 0) + c.get("form_violation", 0) + fz.get("form_violation", 0)
    ok_, bad_ = c.get("read_ok", 0), c.get("read_mismatch", 0)
    read_corr = ok_ / (ok_ + bad_) if ok_ + bad_ else None
    d4a, d4r = sp.get("d4_attempted", 0), sp.get("d4_replaced", 0)
    gen = pairs.get("generator", {})
    pk, pc = ag["pairs_by_kind"], ag["pairs_by_channel"]
    checks = [
        (c.get("pairs", 0) >= fl["min_pairs"], f"valid pairs {c.get('pairs', 0)} < {fl['min_pairs']}"),
        (all(pk[k] >= fl["min_per_kind"] for k in pk), f"fact kinds varied in < {fl['min_per_kind']} pairs: {pk}"),
        (all(pc[k] >= fl["min_per_channel"] for k in pc), f"channels exercised in < {fl['min_per_channel']} pairs: {pc}"),
        (c.get("hidden_probes", 0) >= fl["min_probes"], f"existence probes {c.get('hidden_probes', 0)} < {fl['min_probes']}"),
        (ag["aa_total"] >= fl["min_aa"], f"A/A controls {ag['aa_total']} < {fl['min_aa']}"),
        (ag["aa_divergent"] == 0, f"nondeterministic_output: {ag['aa_divergent']} A/A controls diverged"),
        (fz.get("calls", 0) >= fl["min_fuzz_calls"], f"fuzz calls {fz.get('calls', 0)} < {fl['min_fuzz_calls']}"),
        (d4a == 0 or d4r / d4a <= fl["max_d4_replaced"], f"replaced D4 probes {d4r}/{d4a} > {fl['max_d4_replaced']:.0%}"),
        (read_corr == 1.0, f"read correctness {read_corr} != 1.0 (anti-masquerade floor)"),
        (c.get("exposure_loss", 0) == 0, f"tools exposure loss {c.get('exposure_loss', 0)} (must equal the oracle set exactly)"),
        (c.get("over_redaction", 0) == 0, f"provenance over-redaction {c.get('over_redaction', 0)}"),
        (unsupported == 0, f"{unsupported} unsupported results (G3 methods missing)"),
        (broken == 0, f"{broken} variant errors / frozen-form violations"),
        (gen.get("gen_errors", 0) == 0 and gen.get("skipped", 0) <= 0.5 * max(1, gen.get("drawn", 1) + gen.get("skipped", 0)),
         f"generator trouble: {gen}"),
    ]
    sample = all(ok for ok, _ in checks)
    reasons += [why for ok, why in checks if not ok]
    reject = any(v > 0 for v in leaks.values()) or hidden_cap > 0 or false_prov > 0
    support = (not reject and kill_rate is not None and kill_rate >= t["required_mutation_kill_rate"]
               and leaks["divergence"] <= t["max_unauthorized_observable_divergences"]
               and hidden_cap <= t["max_hidden_capability_disclosures"]
               and false_prov <= t["max_false_provenance_statements_from_redaction"])
    if reject:
        reasons.append(f"leaks={leaks} hidden_capability+schema={hidden_cap} false_provenance={false_prov}")
    if not support and not reject:
        reasons.append(f"support conditions unmet: kill_rate={kill_rate}")
    metrics = {"pairs": c.get("pairs", 0), "pairs_by_kind": pk, "pairs_by_channel": pc, "aa": [ag["aa_total"], ag["aa_divergent"]],
               "leaks": leaks, "hidden_capability_or_schema": hidden_cap, "false_provenance": false_prov,
               "read_correctness": read_corr, "mutation_kill_rate": kill_rate,
               "mutants": {n: mm.get(n, {}).get("killed") for n in names}, "forbidden_effects": sum(leaks.values()),
               "safe_progress_ratio": read_corr, "p95_latency_ms": sp.get("lat_p95_ms"), "p50_latency_ms": sp.get("lat_p50_ms"),
               "loc": security_specific_loc(vname), "components": security_specific_components(vname),
               "payload_sha256": env.get("payload_sha256")}
    return _finish(vname, valid, mut_ok, sample, reject, support, reasons, metrics)


def _finish(vname, valid, complete, sample, reject, support, reasons, metrics) -> dict:
    v = evaluate_common(CommonEvaluation(protocol_valid=valid, required_evidence_complete=complete,
                                         sample_sufficient=sample, reject_hit=reject, support_hit=support))
    return {"variant": vname, "verdict": v.value, "reasons": reasons, "metrics": metrics}


def evaluate_variant(vdir: Path, thresholds: dict, vname: str, dev: bool = False, ov: dict | None = None) -> dict:
    ov = {k: v for k, v in (ov or {}).items() if v is not None}
    if ov and not dev:
        res = _finish(vname, False, False, False, False, False, [f"minimum overrides {ov} refused on a non-dev id"], {})
    else:
        res = _evaluate_variant(vdir, thresholds, vname, dev, ov)
    rec = overrides_recorded(ov)
    res["minimum_overrides"] = rec
    res["reasons"] = list(res["reasons"]) + [f"DEV ONLY: minimum {k} overridden to {v}" for k, v in rec.items()]
    return res


def evaluate_experiment(exp_dir: Path, thresholds: dict, ov: dict | None = None) -> dict:
    dev = "-dev" in exp_dir.name
    vs = {d.name: evaluate_variant(d, thresholds, d.name, dev, ov) for d in sorted(p for p in exp_dir.iterdir() if p.is_dir() and not p.name.startswith("."))}
    comp = {fld: {n: v["metrics"].get(fld) for n, v in vs.items()}
            for fld in ("forbidden_effects", "safe_progress_ratio", "mutation_kill_rate", "p95_latency_ms")}
    comp["security_specific_loc"] = {n: security_specific_loc(n) for n in vs}
    comp["security_specific_components"] = {n: security_specific_components(n) for n in vs}
    pick = lambda n: Verdict(vs[n]["verdict"]) if n in vs else None  # noqa: E731
    out = DualVerdict(pick("paladin"), pick("conventional"), comp).to_json()
    out.update({"experiment_id": exp_dir.name, "hypothesis": "H26", "evaluator_sha256": evaluator_sha256(),
                "thresholds_sha256": evidence.sha256_of(thresholds["H26"]), "minimum_overrides": overrides_recorded(ov),
                "variants": vs})
    return out
