"""P12: H24/H27 evaluators compare frozen spec hashes against protocol/FREEZE_G2.json (tampered copy -> INVALID)."""
import json
import shutil
from pathlib import Path

import pytest

from r3_harness.h24 import evaluator as ev24
from r3_harness.h27 import evaluator as ev27

ROUND3 = Path(__file__).resolve().parents[1]
TH = json.loads((ROUND3 / "protocol" / "thresholds.json").read_text())


def mirror(tmp_path):
    root = tmp_path / "round3"
    (root / "protocol").mkdir(parents=True)
    shutil.copy(ROUND3 / "protocol" / "FREEZE_G2.json", root / "protocol")
    for rel in json.loads((ROUND3 / "protocol" / "FREEZE_G2.json").read_text())["files"]:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROUND3 / rel, root / rel)
    return root


def test_real_tree_matches_freeze_g2():
    assert ev24.freeze_g2_mismatches() == []  # control (a green control keeps the negative below meaningful)


@pytest.mark.parametrize("rel", ["spec/protections/PROT-H24.md", "spec/protections/PROT-H27.md", "spec/gate2/OPEN-QUESTIONS.md"])
def test_tampered_copy_is_reported(tmp_path, monkeypatch, rel):
    root = mirror(tmp_path)
    monkeypatch.setattr(ev24, "ROUND3", root)
    assert ev24.freeze_g2_mismatches() == []
    (root / rel).write_text((root / rel).read_text() + "\nedit\n")
    bad = ev24.freeze_g2_mismatches()
    assert len(bad) == 1 and bad[0].startswith(rel)


def test_missing_frozen_file_is_a_mismatch(tmp_path, monkeypatch):
    root = mirror(tmp_path)
    (root / "spec/gate2/PROTOCOL-P1d.md").unlink()
    monkeypatch.setattr(ev24, "ROUND3", root)
    assert len(ev24.freeze_g2_mismatches()) == 1


def test_evaluators_are_invalid_with_the_reason_on_a_tampered_tree(tmp_path, monkeypatch):
    root = mirror(tmp_path)
    p = root / "spec/protections/PROT-H24.md"
    p.write_text(p.read_text() + "x")
    monkeypatch.setattr(ev24, "ROUND3", root)
    empty = tmp_path / "vdir"
    empty.mkdir()
    r24 = ev24.evaluate_variant(empty, TH, "v") if hasattr(ev24, "evaluate_variant") else ev24._evaluate_variant(empty, TH, "v")
    r27 = ev27.evaluate_variant(empty, TH, "v")
    for r in (r24, r27):
        assert r["verdict"] == "INVALID" and any("frozen G2 spec changed" in x for x in r["reasons"]), r["reasons"]


def test_envelope_prot_hash_is_compared_with_freeze_g2_not_disk(monkeypatch):
    h = ev24.freeze_g2()["spec/protections/PROT-H24.md"]
    assert ev24.frozen_prot_hash() == (h, "protocol/FREEZE_G2.json")
