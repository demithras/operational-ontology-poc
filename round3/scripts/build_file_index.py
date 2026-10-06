#!/usr/bin/env python3
from pathlib import Path
import hashlib

ROOT = Path(__file__).resolve().parents[1]
out = ROOT / "FILE_INDEX.sha256"
rows = []
for path in sorted(ROOT.rglob("*")):
    parts = path.relative_to(ROOT).parts
    if parts and (parts[0] == ".venv" or "__pycache__" in parts or parts[-1].endswith(".egg-info") or any(p.endswith(".egg-info") for p in parts)):
        continue
    if not path.is_file() or path == out or path.name == "FREEZE.json":
        continue
    rel = path.relative_to(ROOT).as_posix()
    rows.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {rel}")
out.write_text("\n".join(rows) + "\n")
print(f"indexed {len(rows)} files")
