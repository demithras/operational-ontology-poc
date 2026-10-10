"""Evaluator verdict paths on real runs of the masquerading fakes + independence check + audit scan + generator sweep."""
import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from r3_harness.h28 import audit, independence
from r3_shared import extcap
from tests.test_h28_e2e import ENV, PY, R3, SIZES


@pytest.fixture(scope="module")
def run():
    root = Path(tempfile.mkdtemp(prefix="h28v"))
    r = subprocess.run([str(R3 / "scripts" / "run_h28.sh"), "--exp-id", "exp-h28-v-dev-1", "--out-root", str(root), "--variants",
                        "fake-FakeAlwaysUnknown,fake-FakeNeverDispatch,paladin", "--test-variants", *SIZES], capture_output=True, text=True,
                       env=ENV, cwd=R3, timeout=900)
    ev = subprocess.run([PY, str(R3 / "scripts" / "evaluate_h28.py"), "exp-h28-v-dev-1", "--out-root", str(root), "--print-only"],
                        capture_output=True, text=True, env=ENV, cwd=R3)
    return r, json.loads(ev.stdout) if ev.stdout.strip() else {}


def test_always_unknown_is_never_supported(run):
    v = run[1]["variants"]["fake-FakeAlwaysUnknown"]
    # never SUPPORTED. The oracle doc sketches INCONCLUSIVE; an always-UNKNOWN variant also misses every target mutation (detection < 1.0),
    # which Q6 maps to REJECTED (precedence REJECTED > INCONCLUSIVE) - reported as a frozen-text tension.
    assert v["verdict"] in ("REJECTED", "INCONCLUSIVE") and v["metrics"]["detection_rate"] == 0.0
    assert v["metrics"]["classes"]["outcome_mismatch"] > 0 and v["metrics"]["classes"]["progress_loss"] > 0


def test_never_dispatch_loses_progress(run):
    v = run[1]["variants"]["fake-FakeNeverDispatch"]
    assert v["verdict"] == "INCONCLUSIVE" and v["metrics"]["classes"]["progress_loss"] > 0
    assert v["metrics"]["classes"]["false_reconciled_success"] == 0


def test_unadopted_seam_is_unsupported_never_supported(run):
    """A registered variant that has not adopted the seam yields `unsupported` harness rows (INCONCLUSIVE), never SUPPORTED."""
    r, ev = run
    if "paladin" not in ev.get("variants", {}):
        assert "not implemented yet - G4" in r.stderr or r.returncode != 0
        return
    v = ev["variants"]["paladin"]
    # G4-E26: paladin has adopted the seam and its twins now match byte-for-byte (the old 445 envelope diffs were a harness artefact), so a
    # tiny dev run may legitimately be SUPPORTED. The invariant that stays: an `unsupported` harness row is NEVER SUPPORTED.
    if v["metrics"].get("harness", {}).get("unsupported"):
        assert v["verdict"] != "SUPPORTED"
    else:
        assert v["verdict"] in ("SUPPORTED", "INCONCLUSIVE"), v["reasons"]


class Obs:
    def __init__(self, key, path):
        self._key, self._path = key, path


class Cl:
    _sock = "/tmp/x/ext.sock"


class Ad:
    adapter_id = "H0"

    def __init__(self, client):
        self.client = client


class B:
    pass


def _binding(obs_key, obs_path, same_client=False):
    b = B()
    root = extcap.mint_root(b"k" * 32, "nn", "ERP", "d")
    cl = Cl()
    obs = Obs(obs_key, obs_path)
    if same_client:
        obs.shared = cl
    b.adapters, b.root_caps, b.observer = {"ERP": Ad(cl)}, {"ERP": root}, obs
    return b, root


def test_independence_check_passes_for_separate_paths_and_flags_shared_ones():
    b, root = _binding("a" * 64, "/tmp/x/external.db")
    assert independence.check(b, "/tmp/x/ext.sock", "d")["shared_trust_root"] is False
    b, root = _binding(root, "/tmp/x/external.db")
    assert independence.check(b, "/tmp/x/ext.sock", "d")["shared_trust_root"] is True            # FakeSharedObserver: key is the root cap
    b, _ = _binding("a" * 64, "/tmp/x/ext.sock")
    assert independence.check(b, "/tmp/x/ext.sock", "d")["shared_trust_root"] is True            # reads through the action socket
    b, _ = _binding("a" * 64, "/tmp/x/external.db", same_client=True)
    assert independence.check(b, "/tmp/x/ext.sock", "d")["shared_trust_root"] is True            # shares the adapter's client object


def test_static_scan_flags_the_policy_gate_and_not_the_honest_adapter_code():
    lits = audit.all_literals()
    assert audit.static_scan("t", ["tests.fakes.fake_h28_policy"], lits, resolutions={})["unresolved_count"] >= 2
    assert audit.static_scan("t", ["tests.fakes.fake_h28_adapt"], lits, resolutions={})["unresolved_count"] == 0


def test_static_scan_resolution_must_match_scope_and_text_and_undeclared_is_reported():
    lits = audit.all_literals()
    r = audit.static_scan("t", ["tests.fakes.fake_h28_policy"], lits, resolutions={})
    h = r["hits"][0]
    res = {audit.hit_key("t", h): "protocol field"}
    r2 = audit.static_scan("t", ["tests.fakes.fake_h28_policy"], lits, resolutions=res)
    assert r2["unresolved_count"] == r["unresolved_count"] - 1 and r2["resolved"]
    assert audit.static_scan("t", None, lits)["declared"] is False
    assert audit.static_scan("t", ["no.such.module"], lits)["unresolved_count"] == 1


def test_scanner_known_negative_and_positive_on_sources():
    lits = audit.all_literals()
    assert audit.scan_source("x.py", "def f(r):\n    return r.body.get('approval')\n", lits)[0]["kind"] == "reply-or-authority-key"
    assert audit.scan_source("x.py", "from conv.policy import gate\n", lits)[0]["kind"] == "import-authority-module"
    assert audit.scan_source("x.py", "def f(p):\n    return p['fee'] > 500\n", lits)[0]["kind"] == "business-rule-literal"
    assert audit.scan_source("x.py", "def f(p):\n    '''docstring about approval'''\n    return 7\n", lits) == []


def test_generator_sweep_20000_cases_10_seeds_no_exception():
    from r3_harness.h28.gen_case import build_case
    from r3_harness.h28.gen_params import draw_params
    n = bad = 0
    for seed in range(10):
        ps, _ = draw_params(seed, 2000)
        st = {}
        for p in ps:
            c = build_case(p, seed, st)
            n += 1
            bad += c is None
    assert n == 20000 and bad / n < 0.01
