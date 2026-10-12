"""The contract evidence files + manifest of one variant (hypotheses/h29/contract.json required_evidence + injection-effectiveness.json)."""
from __future__ import annotations

import gzip
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

from r3_shared import evidence

from . import aggregate, judge

ROUND3 = Path(__file__).resolve().parents[3]
MANIFEST = "manifest.json"
FREEZE_G5 = ROUND3 / "protocol" / "FREEZE_G5.json"
FILES = ("fault-sequences.jsonl", "safety-invariants.json", "safe-progress.json", "explicit-unavailability.json", "recovery-differential.json",
         "mutation-results.json", "injection-effectiveness.json")
GZ_ABOVE = 2_000_000


def _dump(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=1, sort_keys=True, default=str) + "\n")


def _seq_line(R: dict, row: dict) -> dict:
    sd = R.get("seq_def") or {}
    return {"id": R["seq"], "stratum": R["stratum"], "seed": sd.get("seed"), "domain": R.get("domain"), "world_digest": row.get("world_digest"),
            "planned_classes": row["planned_classes"], "steps": sd.get("steps"), "class_windows": sd.get("class_windows"),
            "kills": R.get("kills"), "faults": R.get("faults"), "requests": [{k: q.get(k) for k in
                ("n", "t", "rid", "k", "op", "cls", "down", "strict", "status", "reason", "dep", "oracle", "committed", "eligible", "progressed", "spurious", "phi")}
                for q in row["req"]], "recovery": row["recovery"], "classes": {c: len(d) for c, d in row["classes"].items()},
            "harness": row["harness"], "boundary": row["boundary"], "dependency_status": None}


def write_sequences(vdir: Path, J: dict) -> str:
    p = vdir / FILES[0]
    with p.open("w") as fh:
        for R, row in zip(J["raws"], J["rows"]):
            fh.write(json.dumps(_seq_line(R, row), sort_keys=True, separators=(",", ":"), default=str) + "\n")
    if p.stat().st_size > GZ_ABOVE:
        raw = p.read_bytes()
        (vdir / "RAW_SHA256.txt").write_text(hashlib.sha256(raw).hexdigest() + "  " + FILES[0] + "\n")
        with gzip.open(str(p) + ".gz", "wb") as g:
            g.write(raw)
        p.unlink()
        return FILES[0] + ".gz"
    return FILES[0]


def safety_file(agg: dict) -> dict:
    cl = agg["classes"]
    return {"classes": {c: cl[c] for c in judge.CLASSES}, "p_totals": {"safety_violations": sum(cl[c]["count"] for c in aggregate.SAFETY),
            "recovery": sum(cl[c]["count"] for c in aggregate.RECOVERY), "misclassified": cl["misclassified_dependency_failure"]["count"]},
            "boundary": agg["boundary"], "sequences": {"env": agg["env_sequences"], "ctrl": agg["ctrl_sequences"], "bnd": agg["bnd_sequences"]}}


def progress_file(agg: dict) -> dict:
    p = agg["progress"]
    ratio = lambda v: None if not v[0] else v[1] / v[0]  # noqa: E731
    return {"overall": {"eligible": p["overall"][0], "progressed": p["overall"][1], "ratio": ratio(p["overall"])},
            "controls": {"eligible": p["ctrl"][0], "progressed": p["ctrl"][1], "ratio": ratio(p["ctrl"])},
            "during_fault": {"eligible": p["during_fault"][0], "progressed": p["during_fault"][1], "ratio": ratio(p["during_fault"])},
            "per_class": {c: {"eligible": v[0], "progressed": v[1], "ratio": ratio(v)} for c, v in p["per_class"].items()},
            "post_recovery": {"eligible": p["post_recovery"][0], "progressed": p["post_recovery"][1], "ratio": ratio(p["post_recovery"])},
            "per_node_unrelated": {n: {"eligible": v[0], "progressed": v[1], "ratio": ratio(v)} for n, v in p["per_node"].items()},
            "outcome_progress_loss": {"checked": p["outcome"][0], "lost": p["outcome"][1]}, "spurious_unavailable": p["spurious"]}


def unavailability_file(J: dict) -> dict:
    rows, per = [], []
    for row in J["rows"]:
        for q in row["req"]:
            if q.get("cls") in ("BLOCKED_BY_DEPENDENCY", "UNRESOLVED") and q.get("down"):
                per.append({"seq": row["seq"], "n": q["n"], "t": q["t"], "rid": q.get("rid"), "cls": q["cls"], "down": q["down"],
                            "status": q["status"], "reason": q["reason"], "dep": q["dep"]})
    return {"requests_with_dependency_down": len(per), "per_request": per[:20000], "misclassification": J["agg"]["misclassification"]}


def recovery_file(J: dict) -> dict:
    ev, tot, ok = [], 0, 0
    for row in J["rows"]:
        for r in (row["recovery"] or {}).get("rc1", []) + (row["recovery"] or {}).get("rc2", []):
            ev.append({"seq": row["seq"], **r})
    rc = J["agg"]["recovery"]
    return {"events": ev, "checks": rc["checks"], "passes": rc["passes"], "equality_ratio": None if not rc["checks"] else rc["passes"] / rc["checks"],
            "restricted_io": [{"seq": r["seq"], **x} for r in J["rows"] for x in r["restricted_io"]]}


def injection_file(J: dict) -> dict:
    inj = J["agg"]["injection"]
    return {"by_key": inj, "hit_rates": {k: (v["enforced"] / v["scheduled"] if v["scheduled"] else None) for k, v in inj.items()}}


def write_all(vdir: Path, J: dict, pre: dict, mutation: dict) -> dict:
    seq_name = write_sequences(vdir, J)
    _dump(vdir / FILES[1], safety_file(J["agg"]))
    _dump(vdir / FILES[2], progress_file(J["agg"]))
    _dump(vdir / FILES[3], unavailability_file(J))
    _dump(vdir / FILES[4], recovery_file(J))
    _dump(vdir / FILES[5], mutation)
    _dump(vdir / FILES[6], injection_file(J))
    out = {f: hashlib.sha256((vdir / f).read_bytes()).hexdigest() for f in (seq_name, *FILES[1:])}
    raw = vdir / "cases.jsonl"
    if raw.exists():
        with gzip.open(str(raw) + ".gz", "wb") as g:
            g.write(raw.read_bytes())
        raw.unlink()
    out["cases.jsonl.gz"] = hashlib.sha256((vdir / "cases.jsonl.gz").read_bytes()).hexdigest()
    return out


def tree_sha(pkg: str) -> str:
    h = hashlib.sha256()
    for f in sorted((ROUND3 / "src" / pkg).rglob("*.py")):
        h.update(f.relative_to(ROUND3).as_posix().encode() + f.read_bytes())
    return h.hexdigest()


def git_head() -> str:
    try:
        return subprocess.check_output(["git", "-C", str(ROUND3), "rev-parse", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001
        return "0" * 40


def seal(vdir: Path, exp_id: str, vname: str, pre: dict, hashes: dict, closes: dict, candidate_pkg: str | None, dev: dict, extra: dict) -> None:
    freeze = json.loads(FREEZE_G5.read_text())["files"] if FREEZE_G5.is_file() else {}
    cur = {f: hashlib.sha256((ROUND3 / f).read_bytes()).hexdigest() for f in freeze if (ROUND3 / f).is_file()}
    env = evidence.build_envelope(
        experiment_id=exp_id, hypothesis_id="H29", git_commit=git_head(),
        environment={"python": sys.version.split()[0], "platform": platform.platform(), "variant": vname},
        seed=pre["seed"], attack_class="A8", oracle_version=tree_sha("r3_oracle"),
        candidate_version=f"{vname}:{tree_sha(candidate_pkg) if candidate_pkg else 'test-fake'}",
        raw_observations={"evidence_sha256": hashes, "variant": vname, "freeze_g5_sha256": cur, "freeze_g5_frozen": freeze, "closes": closes,
                          "dev_overrides": dev, "sizes": pre["sizes"], "workers": pre["workers"], "oracle_inputs": [
                              "world_log(shared store)", "authority.db(closed)", "anchor.log(closed)", "external.db(closed)", "harness input log"],
                          **extra})
    (vdir / MANIFEST).write_text(json.dumps(env, indent=1, sort_keys=True) + "\n")
