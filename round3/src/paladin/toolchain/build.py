"""Build a generated surface package from an IR package: sdk.py, caps.py, surface.py (+ the inventory the manifest reports)."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

from paladin.ir import validate

from . import gen_caps, gen_sdk, gen_surface
from .naming import ident


def ir_sha(ir: dict) -> str:
    return hashlib.sha256(json.dumps(ir, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build(ir: dict, out_dir, name: str | None = None) -> dict:
    """Write <out_dir>/<name>/{__init__,sdk,caps,surface}.py. Returns the build inventory (file hashes, tool names)."""
    errs = validate(ir)
    if errs:
        raise ValueError(f"IR does not validate: {errs[:3]}")
    name = name or "gen_" + ident(ir["package_id"])
    pkg = Path(out_dir) / name
    pkg.mkdir(parents=True, exist_ok=True)
    sha = ir_sha(ir)
    surface_text, tools = gen_surface.generate(ir)
    files = {"__init__.py": f'"""Generated surface for {ir["package_id"]} {ir["version"]}."""\n', "sdk.py": gen_sdk.generate(ir, sha),
             "caps.py": gen_caps.generate(ir), "surface.py": surface_text}
    for fn, text in files.items():
        (pkg / fn).write_text(text)
    return {"package": name, "dir": str(pkg), "ir_sha256": sha, "package_id": ir["package_id"], "package_version": ir["version"],
            "files": {fn: {"sha256": hashlib.sha256(t.encode()).hexdigest(), "lines": t.count("\n")} for fn, t in files.items()},
            "tools": tools}


_N = 0


def load_generated(out_dir, name: str):
    """Import a built package under a unique alias; returns (sdk, caps, surface) modules."""
    global _N
    _N += 1
    alias = f"{name}__{_N}"
    pkg = Path(out_dir) / name
    spec = importlib.util.spec_from_file_location(alias, pkg / "__init__.py", submodule_search_locations=[str(pkg)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    import importlib as _il
    return (_il.import_module(alias + ".sdk"), _il.import_module(alias + ".caps"), _il.import_module(alias + ".surface"))
