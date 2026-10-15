"""Vendoring integrity: originals match Round 2 at the pin; every local change is recorded as a documented patch."""
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PAL = ROOT / "round3" / "src" / "paladin"
M = json.loads((PAL / "VENDORED.json").read_text())


def sha(b):
    return hashlib.sha256(b).hexdigest()


def test_originals_match_round2_working_tree_and_pin():
    assert M["upstream_pin"].startswith("8f9ff26")
    for rel, rec in M["files"].items():
        assert sha((ROOT / rec["original"]).read_bytes()) == rec["original_sha256"], rel
    out = subprocess.run(["git", "-C", str(ROOT), "diff", "--stat", M["upstream_pin"], "HEAD", "--", "round2"],
                         capture_output=True, text=True)
    assert out.returncode == 0 and out.stdout.strip() == "", "round2 differs from the upstream pin"


def test_every_change_to_vendored_code_is_a_recorded_patch():
    changed = []
    for rel, rec in M["files"].items():
        now = sha((PAL / rel).read_bytes())
        assert now == rec["current_sha256"], f"{rel} changed since the manifest was refreshed (run scripts/paladin_vendor_manifest.py)"
        if now != rec["vendored_sha256"]:
            changed.append(rel)
            assert rec["patches"], f"{rel} was modified without a recorded patch id"
    assert changed, "expected the documented patches to be present"
    doc = (ROOT / "round3" / "spec" / "protections" / "H23-paladin.md").read_text()
    for rel in changed:
        for pid in M["files"][rel]["patches"]:
            assert f"`{pid}`" in doc, f"patch {pid} ({rel}) is not documented in H23-paladin.md"


def test_no_round2_eoo_imports_remain():
    for f in PAL.rglob("*.py"):
        text = f.read_text()
        for bad in ("from eoo_", "import eoo_", "from domains.", "from hdd."):
            assert bad not in text, (f, bad)
