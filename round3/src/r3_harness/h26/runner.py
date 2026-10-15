"""Per-variant H26 run -> evidence files + envelope (ORACLE-AND-HARNESS-G3 B5)."""
from __future__ import annotations

import gzip
import hashlib
import inspect
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

from r3_shared import evidence

from . import analyze, fuzz, gen_pair, mutation, observe

ROUND3 = Path(__file__).resolve().parents[3]
FILES = ("noninterference-pairs.json", "exfiltration-fuzz.json", "tool-schema-disclosure.json",
         "provenance-redaction.json", "mutation-results.json", "safe-progress.json")
EXTRA = ("noninterference-pairs.jsonl.gz",)


def tree_sha(pkg: str) -> str:
    h = hashlib.sha256()
    for f in sorted((ROUND3 / "src" / pkg).rglob("*.py")):
        h.update(f.relative_to(ROUND3).as_posix().encode() + f.read_bytes())
    return h.hexdigest()


def sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _dump(p: Path, o) -> None:
    p.write_text(json.dumps(o, indent=1, sort_keys=True, default=str) + "\n")


def run_pairs(variant, seed: int, n_pairs: int, aa_n: int, budget_s: float | None = None):
    """Draw until n_pairs valid pairs + aa_n A/A pairs ran. Returns (rows, stats)."""
    rows, st = [], {"redraws": 0, "skipped": 0, "d4_attempted": 0, "d4_replaced": 0, "gen_errors": 0, "drawn": 0}
    t0, idx, got, got_aa = time.time(), 0, 0, 0
    while (got < n_pairs or got_aa < aa_n) and idx < 20 * (n_pairs + aa_n) + 50:
        aa = got >= n_pairs
        p, s = gen_pair.draw(seed, idx + (10 ** 6 if aa else 0), aa=aa)
        idx += 1
        for k in ("redraws", "skipped", "d4_attempted", "d4_replaced"):
            st[k] += s[k]
        st["gen_errors"] += "gen_error" in s
        if p is None:
            continue
        st["drawn"] += 1
        runs = [observe.run_world(variant, p, w) for w in (0, 1)]
        rows.append(analyze.pair_row(p, runs))
        got, got_aa = (got + (not aa), got_aa + aa)
        if budget_s and time.time() - t0 > budget_s:
            break
    return rows, st


def _pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else None


def write_evidence(out: Path, rows: list, st: dict, fz: dict, mut: dict) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    gz = out / EXTRA[0]
    with gzip.open(gz, "wt") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True, separators=(",", ":"), default=str) + "\n")
    ag = analyze.aggregate(rows)
    c = ag["counts"]
    _dump(out / FILES[0], {"pairs_file": EXTRA[0], "pairs_sha256": sha_file(gz), "aggregate": ag, "generator": st,
                           "divergent": [{k: r[k] for k in ("id", "kinds", "domain", "divergences", "witness")}
                                         for r in rows if r["divergences"]][:200]})
    _dump(out / FILES[1], fz)
    _dump(out / FILES[2], {"expected_vs_listed": {k: c.get(k, 0) for k in ("hidden_capability", "schema_disclosure", "exposure_loss", "exposure_ok")},
                           "pairs": ag["counts"].get("pairs", 0)})
    _dump(out / FILES[3], {k: v for k, v in c.items() if k.split(":")[0] in ("false_provenance", "over_redaction", "provenance_overdisclosure", "prov_ok", "form_violation")})
    _dump(out / FILES[4], mut)
    lat = [x for r in rows for ls in r["lat"] for x in ls]
    ok, bad = c.get("read_ok", 0), c.get("read_mismatch", 0)
    _dump(out / FILES[5], {"read_ok": ok, "read_mismatch": bad, "read_correctness": (ok / (ok + bad)) if ok + bad else None,
                           "exposure_loss": c.get("exposure_loss", 0), "over_redaction": c.get("over_redaction", 0),
                           "d4_ok": c.get("d4_ok", 0), "progress_loss": c.get("progress_loss", 0),
                           "d4_attempted": st["d4_attempted"], "d4_replaced": st["d4_replaced"],
                           "lat_p50_ms": _pct(lat, 0.5), "lat_p95_ms": _pct(lat, 0.95)})
    return ag


def seal(out: Path, exp_id: str, vname: str, seed: int, candidate_pkg: str | None, extra: dict) -> None:
    raw = {f: sha_file(out / f) for f in FILES + EXTRA}
    freeze = json.loads((ROUND3 / "protocol/FREEZE_G3.json").read_text())["files"]
    try:
        head = subprocess.check_output(["git", "-C", str(ROUND3), "rev-parse", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001
        head = "0000000"
    prot = ROUND3 / "spec/protections/PROT-H26.md"
    low = ROUND3 / "src/r3_oracle/lowproj.py"
    env = evidence.build_envelope(
        experiment_id=exp_id, hypothesis_id="H26", git_commit=head,
        environment={"python": sys.version.split()[0], "platform": platform.platform(), "variant": vname},
        seed=seed, attack_class="A5", oracle_version=tree_sha("r3_oracle"),
        candidate_version=f"{vname}:{tree_sha(candidate_pkg) if candidate_pkg else 'test-fake'}",
        raw_observations={"evidence_sha256": raw, "variant": vname, "prot_h26_sha256": sha_file(prot),
                          "lowproj_sha256": sha_file(low), "frozen_prot_h26_sha256": freeze["spec/protections/PROT-H26.md"],
                          "canonical_bytes_source_sha256": hashlib.sha256(inspect.getsource(evidence.canonical_bytes).encode()).hexdigest(),
                          **extra})
    evidence.write_envelope(out / "envelope.json", env)


def run_variant(factory, vname: str, out: Path, exp_id: str, seed: int, n_pairs: int, aa_n: int, fuzz_calls: int,
                mut_pairs: int, candidate_pkg: str | None = None, budget_s: float | None = None, overrides: dict | None = None) -> dict:
    variant = factory(())
    rows, st = run_pairs(variant, seed, n_pairs, aa_n, budget_s)
    fz = fuzz.run(variant, seed, fuzz_calls)
    mut = mutation.prove(factory, seed, mut_pairs)
    write_evidence(out, rows, st, fz, mut)
    seal(out, exp_id, vname, seed, candidate_pkg, {"requested": {"pairs": n_pairs, "aa": aa_n, "fuzz_calls": fuzz_calls,
                                                                  "mut_pairs": mut_pairs}, "overrides": overrides or {}})
    return {"pairs": len(rows), "variant": vname}
