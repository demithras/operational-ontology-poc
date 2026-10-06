"""Context-not-trend facts read from COMMITTED evidence (never recomputed, never used as a verdict input except the fairness check)."""
from __future__ import annotations

import json
from pathlib import Path

from eoo_exp.util import ROOT, git, sha_file

H15_METRICS = "experiments/h15/exp-h15-002/compiler-diff-metrics.json"
H18_METRICS = "experiments/h18/exp-h18-001/bespoke-change-metrics.json"
H18_VERDICT = "experiments/h18/exp-h18-001/verdict.json"
H15_VERDICT = "experiments/h15/exp-h15-002/verdict.json"
SNAP_KEYS = ("assignment", "per_class", "recurring_complexity_loc", "python_unassigned_lines", "normalisation", "decision_rule", "engine_version")
LOC_DIRS = ("src/eoo_engine", "src/eoo_engine_git", "src/eoo_toolchain")


def _payload(rel: str, root: Path) -> dict:
    return json.loads((root / rel).read_text())["payload"]


def loc(root: Path = ROOT) -> dict:
    out = {}
    for d in LOC_DIRS:
        files = sorted((root / d).glob("*.py"))
        lines = [ln for f in files for ln in f.read_text().splitlines()]
        out[d] = {"files": len(files), "lines": len(lines), "non_blank_lines": sum(1 for ln in lines if ln.strip())}
    return out


def h18_snapshot(root: Path = ROOT) -> dict:
    p = _payload(H18_METRICS, root)
    snap = {k: p[k] for k in SNAP_KEYS}
    snap["recurring_complexity_loc"] = {k: p["recurring_complexity_loc"][k] for k in ("baseline", "eoo")}
    return snap


def context(root: Path = ROOT) -> dict:
    h15, h18 = _payload(H15_METRICS, root), _payload(H18_METRICS, root)
    verdicts = {k: json.loads((root / rel).read_text())["verdict"] for k, rel in (("H15", H15_VERDICT), ("H18", H18_VERDICT))}
    return {
        "label": "CONTEXT, NOT TREND: single-domain / single-task-set measurements already committed; no marginal slope can be read from them",
        "sources": {rel: {"sha256": sha_file(root / rel), "git_tag": tag} for rel, tag in ((H15_METRICS, "r2-h15-exp002"), (H18_METRICS, "r2-h18-exp001"))},
        "committed_verdicts": verdicts,
        "h15_openpona_over_dsl_ratios": {d["domain"]: d["ratio_openpona_over_dsl"] for d in h15["domains"]},
        "h15_compiler_loc": {"dsl": h15["compiler_loc"]["dsl"]["total"], "openpona": h15["compiler_loc"]["openpona"]["total"]},
        "h18_ratio_eoo_over_baseline_by_class": {c: r["ratio_eoo_over_baseline"] for c, r in sorted(h18["per_class"].items())},
        "h18_totals_loc": {c: {"baseline": r["baseline"]["total"], "eoo": r["eoo"]["total"]} for c, r in sorted(h18["per_class"].items())},
        "h18_recurring_complexity_loc": {k: h18["recurring_complexity_loc"][k] for k in ("baseline", "eoo")},
        "engine_toolchain_loc": loc(root),
        "git_head_at_read": git("rev-parse", "HEAD").strip(),
    }
