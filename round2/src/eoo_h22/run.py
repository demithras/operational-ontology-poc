"""H22 development run: writes the seven evidence files (six JSON records + tradeoff-frontier.md). Refuses to overwrite."""
from __future__ import annotations

import json
from pathlib import Path

from eoo_exp import provenance as prov
from eoo_exp.outdir import immutable_dir
from eoo_exp.util import ROOT, canon, sha_text

from . import facts, payloads

HID = "H22"
JSON_REQUIRED = ["domain-manifest.json", "blind-task-results.json", "adaptation-costs.json", "correctness-security.json", "runtime-tax.json", "trend-analysis.json"]
REQUIRED = [*JSON_REQUIRED, "tradeoff-frontier.md"]
HARNESS = [*sorted((ROOT / "src/eoo_h22").glob("*.py")), *sorted((ROOT / "src/eoo_exp").glob("*.py")), *sorted((ROOT / "oracles/h22").glob("*.py")),
           ROOT / "scripts/run_h22.py", ROOT / "scripts/evaluate_h22.py"]


def build_payloads() -> dict:
    ctx, snap = facts.context(), facts.h18_snapshot()
    return {"domain-manifest.json": payloads.domain_manifest(), "blind-task-results.json": payloads.blind_task_results(),
            "adaptation-costs.json": payloads.adaptation_costs(), "correctness-security.json": payloads.correctness_security(),
            "runtime-tax.json": payloads.runtime_tax(ctx, snap), "trend-analysis.json": payloads.trend_analysis(), "_md": payloads.frontier_md(ctx)}


def run(seed: int, out_root: Path, exp_id: str) -> dict:
    pre = prov.preflight()
    pl = build_payloads()
    corpus = sha_text(canon({k: v for k, v in pl.items() if k != "_md"}))
    p = prov.provenance(pre, exp_id, HID, seed, corpus, HARNESS, engine_version="1.1")
    with immutable_dir(out_root, exp_id) as tmp:
        for f in JSON_REQUIRED:
            prov.write(tmp, f, prov.wrap(p, f[:-5], pl[f]))
        (tmp / "tradeoff-frontier.md").write_text(pl["_md"])
    return {"corpus_hash": corpus, "real_domains": pl["domain-manifest.json"]["real_domain_count"], "blind_tasks": 0}
