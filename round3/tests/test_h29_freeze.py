"""Freeze manifest (ORACLE-AND-HARNESS-G5 s9): the mechanism, and the REAL state (red until the orchestrator adds the manifest files to FREEZE_G5
in the commit that records them - Q16; src/ and spec/ files are mine, protocol/FREEZE_G5.json is not)."""
import hashlib
import json

from r3_harness.h29 import evalchecks as EC


def test_manifest_mechanism(tmp_path):
    f = tmp_path / "FREEZE_G5.json"
    want = EC.manifest_paths()
    present = [p for p in want if (EC.ROUND3 / p).is_file()]
    f.write_text(json.dumps({"files": {p: EC.sha(p) for p in present[:-1]}}))
    ms = EC.manifest_state(f)
    assert ms["missing_from_freeze"] == sorted(set(want) - set(present[:-1]))
    f.write_text(json.dumps({"files": {p: EC.sha(p) for p in present} | {"nope/missing.json": "0" * 64}}))
    ms = EC.manifest_state(f)
    assert ms["freeze_paths_missing_on_disk"] == ["nope/missing.json"] and not [p for p in ms["missing_from_freeze"] if p in present]
    f.write_text(json.dumps({"files": {present[0]: "0" * 64}}))
    frozen, cur = EC.freeze_state(f)
    assert frozen[present[0]] != cur[present[0]]


def test_manifest_lists_every_invalid_if_file_and_the_family():
    want = set(EC.manifest_paths())
    assert set(EC.HASH_CLAUSE_C) <= want
    assert {"src/r3_harness/h29/evaluator.py", "src/r3_oracle/continuity.py", "src/r3_oracle/recoverymodel.py", "src/r3_harness/h28/adapters.py"} <= want
    fam = [p for p in want if p.startswith("spec/gate5/authority-versions/")]
    assert len(fam) >= 20 and all((EC.ROUND3 / p).is_file() for p in fam)


def test_real_freeze_g5_covers_the_manifest():
    """RED until protocol/FREEZE_G5.json lists every manifest file (the orchestrator freezes them; the list + sha256 is in the g5-harness report)."""
    ms = EC.manifest_state()
    assert not ms["missing_from_freeze"], ms["missing_from_freeze"][:10]
    assert not ms["freeze_paths_missing_on_disk"], ms["freeze_paths_missing_on_disk"]
    frozen, cur = EC.freeze_state()
    assert all(cur[p] == h for p, h in frozen.items()), [p for p, h in frozen.items() if cur.get(p) != h]
