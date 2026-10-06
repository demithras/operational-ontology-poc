"""Hypothesis profiles (dev / ci) and a synthetic known-positive evidence directory for the H17 evaluator tests."""
import json
import os
import shutil
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

CLASSES = ["read", "function_call", "propose", "approve", "deny", "retry", "crash_restart", "execute", "observe_outcome",
           "unauthorized", "stale_or_invalid"]
DOMAINS = ("manufacturing", "project")


def _attack(domain, name, category, violation=False, expected_change=False):
    return {"attack": name, "category": category, "domain": domain, "world_changed": expected_change, "refused": not violation,
            "exception": None, "unexpected_exception": False, "expected_change": expected_change, "violation": violation,
            "detail": "synthetic"}


def synthetic_payloads() -> dict:
    from eoo_exp.util import sha_file
    cases = [{"domain": d, "profile": "std", "sha": f"{d}-{i}", "n_steps": 5, "classes": list(CLASSES), "function_only": i % 10 == 0}
             for d in DOMAINS for i in range(3100)]
    fn = [{"domain": d, "profile": "std", "sha": f"fn-{d}-{i}", "n_steps": 3, "function_calls": 3, "refused_calls": 0,
           "effect_log_before": 0, "effect_log_after": 0, "effect_digest_equal": True, "store_equal": True, "external_before": 0,
           "external_after": 0, "external_equal": True, "identical": True} for d in DOMAINS for i in range(1100)]
    neg = [{"case": "denied:unauthorized", "domain": d, "profile": "std", "scenario": "s", "kind": "unauthorized", "via": "engine",
            "adapter_mode": "ok", "final_state": "DENIED", "failed_gates": ["authority"], "expected_gate": "authority",
            "effect_log_delta": 0, "external_delta": 0, "store_equal": True, "zero_effects": True} for d in DOMAINS]
    attacks = []
    for d in DOMAINS:
        attacks += [_attack(d, "request_forbidden_kinds", "raw_write"), _attack(d, "control_no_tamper", "tamper"),
                    _attack(d, "tamper_returned_record", "tamper"), _attack(d, "interpreter_introspection_probe", "disclosed_limit")]
    muts = [{"id": f"M{i}", "class": c, "target": True, "expected_kinds": ["function_effect"], "killed": True,
             "killed_by_expected_signal": True, "killed_in_domains": {}, "examples_run": {},
             "counterexample": {"domain": "manufacturing", "kind": "function_effect", "steps": [["init", "std"], ["function_call"]],
                                "n_steps": 1}} for i, c in enumerate(["function_write", "function_write", "gate_bypass", "gate_bypass"])]
    return {
        "state-machine-results.json": {
            "oracle": {"file": "oracles/h17/model.py", "sha256": sha_file(ROOT / "oracles/h17/model.py"), "imports": ["dataclasses"],
                       "forbidden_imports": []},
            "engine_files": {"paths_dirty": [], "clean": True}, "config": {"seed": 1},
            "per_domain": {d: {"examples_executed": 3300, "chunks": 2, "unique": 3100, "failures": []} for d in DOMAINS},
            "cases": cases},
        "effect-log-audit.json": {"function_only_traces": fn},
        "negative-action-results.json": {"negative_cases": neg, "agent_attacks": attacks,
                                         "baseline_contextual": {"violations": 2, "attacks": []}},
        "mutation-results.json": {"controls": {"clean": True, "clean_after_restore": True}, "mutants": muts, "summary": {}}}


@pytest.fixture(scope="session")
def positive_dir(tmp_path_factory):
    from eoo_exp import provenance as prov
    from eoo_h17.run import REQUIRED
    d = tmp_path_factory.mktemp("h17pos") / "pos"
    d.mkdir()
    pre = prov.preflight()
    p = prov.provenance(pre, "pos", "H17", 17, "corpus", [])
    pl = synthetic_payloads()
    for fn in REQUIRED:
        prov.write(d, fn, prov.wrap(p, fn[:-5], pl[fn]))
    return d


@pytest.fixture()
def edit(positive_dir, tmp_path):
    """edit(filename, fn) -> new evidence dir where fn(payload) edited that file's payload (hash refreshed)."""
    from eoo_exp import provenance as prov
    from eoo_exp.util import canon, sha_text

    def _edit(filename=None, fn=None, record_fn=None, drop=None):
        dst = tmp_path / "ev"
        shutil.copytree(positive_dir, dst)
        if drop:
            (dst / drop).unlink()
        if filename:
            rec = json.loads((dst / filename).read_text())
            if fn:
                fn(rec["payload"])
                rec["payload_hash"] = sha_text(canon(rec["payload"]))
            if record_fn:
                record_fn(rec)
            prov.write(dst, filename, rec)
        return dst
    return _edit
