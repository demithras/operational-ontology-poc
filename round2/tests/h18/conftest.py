"""Hypothesis profiles (dev / ci), import path for round2, and shared rig fixtures for the H18 tests."""
import os
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


@pytest.fixture(scope="session")
def reader():
    from domains.project.logic.freeze import git_blob_reader
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    return git_blob_reader(head)


@pytest.fixture(scope="session")
def rig(reader, tmp_path_factory):
    from eoo_h18.rig import EooRig
    return EooRig(tmp_path_factory.mktemp("h18rig"), reader=reader)


@pytest.fixture(scope="session")
def rig_v2(reader, tmp_path_factory):
    """The Project contract v2 (exp-h18-001's candidate): used where a v2 behaviour is pinned (findings, v2-red tests)."""
    from eoo_h18.rig import EooRig
    return EooRig(tmp_path_factory.mktemp("h18rig_v2"), reader=reader, ir_version="v2")


@pytest.fixture(scope="session")
def small_run(tmp_path_factory):
    """A REAL (tiny) H18 run: real provenance, hashes and payload shapes; the evaluator tests edit copies of it."""
    from eoo_h18 import run as runner
    root = tmp_path_factory.mktemp("h18small")
    runner.run(3, 12, root, "small", mut_n=12, log=lambda m: None)
    return root / "small"


@pytest.fixture(scope="session")
def positive_dir(small_run, tmp_path_factory):
    """Known-positive: the real small run with its corpus padded to 3,000 unique cases covering every class, and the numbers that
    only a full run can show (mutants killed, a task class >= 25% lower) written in. Every edit refreshes the payload hash."""
    import json
    import shutil
    from eoo_exp import provenance as prov
    from eoo_exp.util import canon, sha_text
    from eoo_h18 import corpus
    dst = tmp_path_factory.mktemp("h18pos") / "pos"
    shutil.copytree(small_run, dst)

    def edit(name, fn):
        rec = json.loads((dst / name).read_text())
        fn(rec["payload"])
        rec["payload_hash"] = sha_text(canon(rec["payload"]))
        prov.write(dst, name, rec)

    def row(op, cls, legal, acc, **kw):
        e = {"acc": acc, "state": "RECONCILED_SUCCESS" if acc else "DENIED", "gate": None if acc else "preconditions", "div": None, "match": True,
             "commits": int(acc), "unchanged": True, "git_only": True, "trace": True if acc else None, "exc": None}
        r = {"op": op, "cls": cls, "legal": legal, "eoo": e, "base": {"acc": acc, "div": None, "match": True, "exc": None}}
        if op == "evaluate" and acc:
            r["verdict"] = "SUPPORTED"
        return r

    def sm(p):
        cases = []
        for i in range(3000):
            steps = [row("evaluate", ["evaluate_with_evidence", "evaluate:legal"], True, True)]
            for k, c in enumerate(corpus.REQUIRED_CLASSES):
                if k % 3 == i % 3:
                    steps.append(row("x", [c], c in ("evidence_pinned_ok", "evaluate_with_evidence", "supersede_ok", "flag_orphan", "preregister", "decision_ok"),
                                     c in ("evidence_pinned_ok", "evaluate_with_evidence", "supersede_ok", "flag_orphan", "preregister", "decision_ok")))
            cases.append({"id": f"c{i:05d}", "subject": "H16", "phase0": "DRAFT", "n_ops": len(steps), "steps": steps, "stopped_eoo": False, "stopped_base": False})
        p["cases"] = cases
        agg = corpus.aggregate(cases)
        p["eoo"], p["evaluations"], p["class_counts"] = agg["eoo"], agg["evaluations"], agg["class_counts"]
        p["corpus"]["unique_cases"] = 3000

    def bm(p):
        for c, v in p["per_class"].items():
            v["baseline"]["total"], v["eoo"]["total"] = 100, 60
            v["correctness"] = {"eoo": True, "baseline": True}
        p["recurring_complexity_loc"] = {"eoo": 10, "baseline": 20, "eoo_files": []}

    def mu(p):
        for m in p["mutants"]:
            m["killed"], m["exceptions"] = True, 0
        p["controls"].update(clean=True, clean_after=True)

    def bc(p):
        p["tc2"]["baseline_correct"] = {"q1": True, "q2": True, "q3": True}
        p["tc3"]["baseline_correct"] = True

    edit("project-state-machine.json", sm)
    edit("bespoke-change-metrics.json", bm)
    edit("mutation-results.json", mu)
    edit("baseline-comparison.json", bc)
    return dst


@pytest.fixture()
def edit(positive_dir, tmp_path):
    """edit(filename, fn, record_fn=None, drop=None) -> new evidence dir where fn(payload) edited that file (hash refreshed)."""
    import json
    import shutil
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
