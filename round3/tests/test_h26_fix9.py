"""G3 fix9: official-id anchor guard (G3-E31b) and valdiff low-equivalence by construction."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from r3_harness.h26 import gen_pair, sim
from r3_oracle import ops_model
from r3_oracle.disclosure import low_view

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def _sh(*a, env_extra=None, drop=()):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), **(env_extra or {})}
    for k in drop:
        env.pop(k, None)
    return subprocess.run(list(a), capture_output=True, text=True, cwd=ROOT, env=env)


def test_official_id_without_anchor_is_refused(tmp_path):
    r = _sh(PY, "scripts/run_h26.py", "--exp-id", "exp-h26-777", "--variants", "fake-honest", "--test-variants", "--out-root", str(tmp_path),
            drop=("R3_ANCHOR_SOCK",))
    assert r.returncode == 2 and "R3_ANCHOR_SOCK" in r.stderr
    assert not (tmp_path / "exp-h26-777").exists()


def test_official_id_with_anchor_passes_the_guard(tmp_path):
    r = _sh(PY, "scripts/run_h26.py", "--exp-id", "exp-h26-777", "--variants", "nonexistent-variant", "--out-root", str(tmp_path),
            env_extra={"R3_ANCHOR_SOCK": str(tmp_path / "nosock")})
    assert "R3_ANCHOR_SOCK" not in r.stderr


def test_run_sh_exports_the_anchor_for_each_variant():
    sh = (ROOT / "scripts/run_h26.sh").read_text()
    assert "run_sandboxed.sh" in sh and 'for V in' in sh
    assert "R3_ANCHOR_SOCK" in (ROOT / "scripts/run_sandboxed.sh").read_text()


def test_dev_id_still_autostarts_an_anchor(tmp_path):
    r = _sh(PY, "scripts/run_h26.py", "--exp-id", "exp-h26-dev", "--variants", "fake-honest", "--test-variants", "--pairs", "5", "--aa", "2",
            "--fuzz-calls", "10", "--mutation-pairs", "2", "--out-root", str(tmp_path), drop=("R3_ANCHOR_SOCK",))
    assert "R3_ANCHOR_SOCK" not in r.stderr and r.returncode == 0, r.stderr[-400:]


def test_p2610_4784_is_no_longer_produced_as_is():
    p, _ = gen_pair.draw(2610, 4784)
    assert p is not None
    d = p["info"].get("D")
    if d and d.get("mode") == "valdiff":
        a1, a2 = d["args"]
        ops = gen_pair.load(p["domain"])[0]
        opd = ops_model.op_of(ops, d["op"])
        assert ops_model.resources_of(opd, a1) == ops_model.resources_of(opd, a2)
    assert not (d and d.get("args") == [{"po_id": "PO-991", "expedite_fee": 500}, {"po_id": "PO-992", "expedite_fee": 500}])


@pytest.mark.parametrize("domain", gen_pair.DOMAINS)
def test_valdiff_pairs_are_low_equivalent_by_the_oracle(domain):
    ops, _a, _g = gen_pair.load(domain)
    base = sim.apply_changes(sim.empty(), [c for b in sim.seed_batches(ops) for c in b])
    n = seed = 0
    while n < 300 and seed < 20000:
        p, st = gen_pair.draw(9000 + seed, 3, kind="D", domain=domain)  # idx 3 -> kind D
        seed += 1
        if p is None or p["info"].get("D", {}).get("mode") != "valdiff":
            continue
        n += 1
        s = [gen_pair._snap_after(base, d, ops, p["auth"]) for d in p["w"]]
        f = [gen_pair._facts(d, p["info"]) for d in p["w"]]
        lv = [low_view(si, p["auth"], p["observer"], ops, fi) for si, fi in zip(s, f)]
        assert lv[0].to_doc() == lv[1].to_doc(), p["id"]
        h1, h2 = p["w"][0]["high"][0], p["w"][1]["high"][0]
        opd = ops_model.op_of(ops, h1["op"])
        for a, b in zip(sorted(ops_model.resources_of(opd, h1["args"])), sorted(ops_model.resources_of(opd, h2["args"]))):
            assert a == b or (f"{a[0]}:{a[1]}" not in lv[0].objects and f"{b[0]}:{b[1]}" not in lv[0].objects), p["id"]
    assert n == 300, (domain, n, seed)


def test_run_sh_dev_run_works_end_to_end_with_the_anchor(tmp_path):
    r = subprocess.run(["scripts/run_h26.sh", "--exp-id", "exp-h26-dev9", "--variants", "paladin", "--pairs", "5", "--aa", "2",
                        "--fuzz-calls", "20", "--mutation-pairs", "1", "--out-root", str(tmp_path)],
                       capture_output=True, text=True, cwd=ROOT, env={**os.environ, "PY": PY})
    assert r.returncode == 0, r.stderr[-400:]
    assert (tmp_path / "exp-h26-dev9" / "paladin" / "envelope.json").exists() and "ANCHOR_CLOSED" in r.stderr
    assert '"entries": 0,' not in r.stderr
