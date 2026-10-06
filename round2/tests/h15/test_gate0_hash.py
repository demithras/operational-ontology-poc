"""The Gate-0 hash script detects change, addition and removal of pinned inputs (known-negatives on a temp copy)."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("gate0", ROOT / "scripts" / "h15_gate0_hash.py")
gate0 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate0)


def _fresh(tmp_path, monkeypatch):
    out = tmp_path / "gate0.json"
    monkeypatch.setattr(gate0, "OUT", out)
    assert gate0.main([]) == 0
    return out


def test_fresh_snapshot_checks_clean(tmp_path, monkeypatch, capsys):
    _fresh(tmp_path, monkeypatch)
    assert gate0.main(["--check"]) == 0


def test_changed_file_is_detected(tmp_path, monkeypatch, capsys):
    out = _fresh(tmp_path, monkeypatch)
    d = json.loads(out.read_text())
    d["files"][0]["sha256"] = "0" * 64
    out.write_text(json.dumps(d))
    assert gate0.main(["--check"]) == 1
    assert "changed" in capsys.readouterr().out


def test_added_and_removed_files_are_detected(tmp_path, monkeypatch, capsys):
    out = _fresh(tmp_path, monkeypatch)
    d = json.loads(out.read_text())
    gone = d["files"].pop()["path"]  # a pinned file the snapshot no longer lists == a new file under the pinned dirs
    d["files"].append({"path": "src/eoo_ir/ghost.py", "sha256": "1" * 64})
    out.write_text(json.dumps(d))
    assert gate0.main(["--check"]) == 1
    msg = capsys.readouterr().out
    assert "added " + gone in msg and "removed src/eoo_ir/ghost.py" in msg


def test_pin_and_combined_hash_tampering_is_detected(tmp_path, monkeypatch, capsys):
    out = _fresh(tmp_path, monkeypatch)
    d = json.loads(out.read_text())
    d["openpona_pin"]["commit"] = "deadbee"
    out.write_text(json.dumps(d))
    assert gate0.main(["--check"]) == 1
    assert "openpona_pin" in capsys.readouterr().out


def test_missing_snapshot_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(gate0, "OUT", tmp_path / "nope.json")
    assert gate0.main(["--check"]) == 1


def test_the_pin_is_the_contracts_pin():
    snap = gate0.snapshot()
    assert snap["openpona_pin"] == json.loads((ROOT / "hypotheses/h15/contract.json").read_text())["experiment"]["openpona_pin"]
    assert snap["openpona_pin"]["commit"] == "97a9b9e"
