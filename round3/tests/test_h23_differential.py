"""R-5: variant-differential replays one recorded corpus on another variant and lists every differing world diff."""
import json
import subprocess
import sys
from pathlib import Path

from r3_harness.h23 import differential
from r3_harness.h23.corpus import load_specs
from r3_harness.h23.runner import FILES, run_variant
from tests.fakes.h23_fakes import FakeDep, FakeVariant

ROUND3 = Path(__file__).resolve().parents[1]
SPECS = load_specs()


class _DropTransfer(FakeDep):
    """Differs from the correct fake on ONE operation: transfer_inventory commits no effects."""

    def _apply(self, effects):
        if getattr(self, "_cur", None) == "transfer_inventory":
            return
        super()._apply(effects)

    def _run(self, token, op, args, obo, rid, backstop):
        self._cur = op
        return super()._run(token, op, args, obo, rid, backstop)


class _FakeDiffering(FakeVariant):
    def __init__(self, mutants=()):
        super().__init__("correct", mutants)

    def deploy(self, domain, factory, verifier, ops_spec, auth_spec, clock, state_dir=None):
        return _DropTransfer("correct", domain, factory, verifier, ops_spec, auth_spec, clock, self.mutants)


def test_differential_lists_exactly_the_calls_of_the_one_differing_operation(tmp_path):
    ref = FakeVariant("correct")
    run_variant(lambda m: FakeVariant("correct", m), "fake-correct", tmp_path / "a", "exp-diff", 5, 30, 10)
    records = differential.load_records(tmp_path / "a" / FILES[0])
    same = differential.compare(records, differential.replay(FakeVariant("correct"), records), "a", "b")
    assert same["calls_compared"] > 100 and same["differing_calls"] == 0  # known negative: identical variants agree
    other = differential.compare(records, differential.replay(_FakeDiffering(), records), "a", "b")
    assert other["differing_calls"] > 0
    assert {d["operation"] for d in other["differences"]} == {"transfer_inventory"}  # known positive, only that op
    assert all(d["a"] and not d["b"] for d in other["differences"])
    assert other["listed"] == len(other["differences"]) <= differential.MAX_LISTED
    assert ref.name == "fake-correct"


def test_run_h23_writes_the_report_only_for_two_variants_and_the_evaluator_ignores_it(tmp_path):
    cmd = [sys.executable, str(ROUND3 / "scripts" / "run_h23.py"), "--test-variants", "--sequences", "20",
           "--mutation-sequences", "5", "--out-root", str(tmp_path)]
    subprocess.run([*cmd, "--exp-id", "one", "--variants", "fake-correct"], check=True, capture_output=True)
    assert not (tmp_path / "one" / "variant-differential.json").exists()
    subprocess.run([*cmd, "--exp-id", "two-dev", "--variants", "fake-correct,fake-allow-all"], check=True, capture_output=True)
    doc = json.loads((tmp_path / "two-dev" / "variant-differential.json").read_text())
    assert doc["informational"] is True and doc["pairs"][0]["reference"] == "fake-correct"
    assert doc["pairs"][0]["differing_calls"] > 0 and doc["pairs"][0]["other"] == "fake-allow-all"
    r = subprocess.run([sys.executable, str(ROUND3 / "scripts" / "evaluate_h23.py"), "two-dev", "--out-root", str(tmp_path),
                        "--min-sequences", "10", "--print-only"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert set(json.loads(r.stdout)["variants"]) == {"fake-correct", "fake-allow-all"}
