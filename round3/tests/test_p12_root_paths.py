"""P12: root-path bug class (H23 runner pointed at the repo root, so the oracle scan and package hash saw nothing)."""
import hashlib
from pathlib import Path

import pytest

from r3_harness.h23 import evaluator as ev23
from r3_harness.h23 import runner as run23
from r3_harness.h24 import runner as run24
from r3_harness.h27 import runner as run27

ROUND3 = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("mod", [run23, run24, run27])
def test_every_harness_runner_roots_at_the_round3_dir(mod):
    assert mod.ROUND3 == ROUND3 and (mod.ROUND3 / "protocol" / "FREEZE.json").is_file()


def test_oracle_scan_visits_files_and_package_hash_is_not_empty_hash():
    assert len(list((ev23.ROUND3 / "src" / "r3_oracle").rglob("*.py"))) > 0
    empty = hashlib.sha256(b"").hexdigest()
    for mod in (run23, run24, run27):
        for pkg in ("r3_oracle", "paladin", "conventional"):
            assert mod.tree_sha(pkg) != empty, (mod.__name__, pkg)


def test_oracle_scan_fails_on_planted_variant_import_known_negative(monkeypatch, tmp_path):
    fake = tmp_path / "src" / "r3_oracle"
    fake.mkdir(parents=True)
    (fake / "bad.py").write_text("import paladin\n")
    monkeypatch.setattr(ev23, "ROUND3", tmp_path)
    ok, bad = ev23.oracle_independent()
    assert not ok and any("imports paladin" in b for b in bad)
    (fake / "bad.py").write_text("import json\n")
    assert ev23.oracle_independent() == (True, [])  # control: clean planted file passes
