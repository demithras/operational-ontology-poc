"""Hypothesis profiles (dev / ci), import path, a REAL gate-closed run (subprocess) and a synthetic evidence builder."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from hypothesis import HealthCheck, settings

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

_SUPPRESS = [HealthCheck.too_slow, HealthCheck.data_too_large, HealthCheck.filter_too_much, HealthCheck.large_base_example]
settings.register_profile("dev", max_examples=200, deadline=None, suppress_health_check=_SUPPRESS, database=None)
settings.register_profile("ci", max_examples=200, deadline=None, derandomize=True, suppress_health_check=_SUPPRESS, database=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))

CLASSES = ["source_churn", "new_relation_query", "policy_composition", "action_addition", "interface_reuse"]


@pytest.fixture(scope="session")
def real_run(tmp_path_factory):
    root = tmp_path_factory.mktemp("h22real")
    r = subprocess.run([sys.executable, str(ROOT / "scripts/run_h22.py"), "--exp-id", "real", "--seed", "3", "--out-root", str(root)],
                       cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-500:] + r.stderr[-500:]
    return root / "real"


def rewrite(d: Path, fname: str, fn) -> None:
    """Edit one record's payload and re-seal its hash, so only the content changed."""
    from eoo_exp.util import canon, sha_text
    rec = json.loads((d / fname).read_text())
    fn(rec["payload"])
    rec["payload_hash"] = sha_text(canon(rec["payload"]))
    (d / fname).write_text(json.dumps(rec, indent=1, sort_keys=True))


def make_case(d: Path, *, domains=3, tasks=30, ratio=0.5, slope=0.5, ci=(0.4, 0.6), noninf=True, tier=True, fair=True, regress=0, class_ratio=None):
    """Turn a copy of the real (gate-closed) run into a synthetic scenario with the given numbers. Domains: D1,D2,... all 'real'."""
    ids = [f"D{i + 1}" for i in range(domains)]

    def mf(p):
        p["real_domains"] = [{"id": i, "name": i, "real": True, "independently_useful": True, "evidence_it_is_real": ["synthetic test fixture"]} for i in ids]
        p["real_domain_count"] = domains

    def bt(p):
        p["tasks"] = [{"task_id": f"t{i}", "domain": ids[i % domains], "task_class": CLASSES[i % 5], "status": "complete"} for i in range(tasks)]
        p["tasks_completed"] = tasks

    def ac(p):
        p["per_task"] = [{"task_id": f"t{i}", "domain": ids[i % domains], "task_class": CLASSES[i % 5], "eoo_cost": 100 * (class_ratio or {}).get(CLASSES[i % 5], ratio),
                          "baseline_cost": 100, "eoo_components": {"config": 1, "glue": 1}, "baseline_components": {"config": 1, "glue": 1}} for i in range(tasks)]

    def cs(p):
        p["per_class"] = {c: {"non_inferior": noninf} for c in CLASSES}
        p["regressions"] = regress

    def rt(p):
        p["realistic_tier_gain_not_dominated_by_tax"] = tier
        p["fair_baseline_savings_persist"] = fair

    def tr(p):
        p.update(slope_ratio=slope, ci_low=ci[0], ci_high=ci[1], domains_in_fit=domains)
    for f, fn in (("domain-manifest.json", mf), ("blind-task-results.json", bt), ("adaptation-costs.json", ac), ("correctness-security.json", cs),
                  ("runtime-tax.json", rt), ("trend-analysis.json", tr)):
        rewrite(d, f, fn)


@pytest.fixture()
def case(real_run, tmp_path):
    d = tmp_path / "ev"
    shutil.copytree(real_run, d)
    (d / "verdict.json").unlink(missing_ok=True)
    return d
