"""Small shared helpers: canonical JSON / hashes, git facts."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # round2/
REPO = ROOT.parent


def canon(x) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha_file(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def git(*args: str, timeout: int = 120) -> str:
    """Read-only git invocation in the repository; raises on a non-zero exit."""
    r = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()[:200]}")
    return r.stdout


def head_commit() -> str:
    return git("rev-parse", "HEAD").strip()


def dirty_paths() -> list[str]:
    """Paths with uncommitted changes, excluding experiment outputs (they are what a run produces)."""
    out = git("status", "--porcelain")
    return sorted(ln[3:] for ln in out.splitlines() if not ln[3:].startswith("round2/experiments/"))


def load_oracle(hid_dir: str, module: str):
    """Import round2/oracles/<hid_dir>/<module>.py by file path (the oracle tree is not on the package path)."""
    import importlib.util
    path = ROOT / "oracles" / hid_dir / f"{module}.py"
    spec = importlib.util.spec_from_file_location(f"oracles_{hid_dir}_{module}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
