"""Kernel snapshots: kernel kinds + Engine DISPATCH_TABLE + ir.schema $defs, from a git revision or the live process."""
from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from eoo_exp.util import REPO, ROOT, git, sha_bytes, sha_text


def dispatch_snapshot() -> dict:
    """Describe the live ``eoo_engine.DISPATCH_TABLE``: kind -> handler class, operations, source fingerprint."""
    import eoo_engine
    from eoo_engine import registry
    table = registry.DISPATCH_TABLE
    out = {}
    for kind, h in table.items():
        try:
            src = inspect.getsource(type(h))
        except (OSError, TypeError):
            src = repr(type(h))
        out[kind] = {"handler": type(h).__qualname__, "handler_kind_attr": getattr(h, "kind", None),
                     "operations": sorted(getattr(h, "ops", {})), "handler_source_sha256": sha_text(src)}
    return {"order": list(table), "handlers": out, "engine_file": str(Path(eoo_engine.__file__).resolve())}


def schema_snapshot(schema_text: str) -> dict:
    s = json.loads(schema_text)
    props = s.get("properties", {})
    arrays = sorted(k for k, v in props.items() if v.get("type") == "array" and "$ref" in v.get("items", {}))
    return {"sha256": sha_text(schema_text), "package_fields": sorted(props), "resource_array_fields": arrays,
            "defs": sorted(s.get("$defs", {})), "additionalProperties": s.get("additionalProperties")}


def live_snapshot(schema_text: str | None = None, prereg_text: str | None = None) -> dict:
    schema_text = schema_text if schema_text is not None else (ROOT / "ontology/ir.schema.json").read_text()
    prereg_text = prereg_text if prereg_text is not None else (ROOT / "protocol/ENGINE_PREREG.json").read_text()
    pre = json.loads(prereg_text)["kernel_snapshot"]
    return {"kernel_resource_kinds": sorted(pre["kernel_resource_kinds"]), "ir_schema": schema_snapshot(schema_text),
            "dispatch": dispatch_snapshot()}


def _dispatch_in_tree(src_dir: Path) -> dict:
    code = ("import json,sys; from eoo_h16.kernel import dispatch_snapshot as d; print(json.dumps(d()))")
    env = {**os.environ, "PYTHONPATH": str(src_dir), "PYTHONDONTWRITEBYTECODE": "1"}
    r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError("dispatch snapshot failed: " + r.stderr[-300:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def rev_snapshot(rev: str) -> dict:
    """Kernel snapshot of git revision ``rev`` (anything ``git rev-parse`` accepts); records the commit SHAs."""
    sha = git("rev-parse", f"{rev}^{{commit}}").strip()
    rel = ROOT.relative_to(REPO).as_posix()
    schema_text = git("show", f"{sha}:{rel}/ontology/ir.schema.json")
    prereg_text = git("show", f"{sha}:{rel}/protocol/ENGINE_PREREG.json")
    with tempfile.TemporaryDirectory() as tmp:
        tar = subprocess.run(["git", "archive", sha, f"{rel}/src"], cwd=REPO, capture_output=True, timeout=120)
        if tar.returncode != 0:
            raise RuntimeError("git archive failed: " + tar.stderr.decode()[:200])
        subprocess.run(["tar", "-x", "-C", tmp], input=tar.stdout, check=True, timeout=120)
        src = Path(tmp) / rel / "src"
        dispatch = _dispatch_in_tree(src)
        if not dispatch["engine_file"].startswith(str(Path(tmp).resolve())):
            raise RuntimeError("snapshot imported the Engine from the wrong tree: " + dispatch["engine_file"])
        core = {p.relative_to(src).as_posix(): sha_bytes(p.read_bytes()) for p in sorted((src / "eoo_engine").glob("*.py"))}
        ir_core = {p.relative_to(src).as_posix(): sha_bytes(p.read_bytes()) for p in sorted((src / "eoo_ir").glob("*.py"))}
    pre = json.loads(prereg_text)["kernel_snapshot"]
    dispatch["engine_file"] = f"<git archive {sha[:12]}>/eoo_engine/__init__.py"  # temp path is not evidence
    return {"git_rev": rev, "git_commit": sha, "ir_schema_blob_sha256": sha_text(schema_text),
            "engine_prereg_blob_sha256": sha_text(prereg_text),
            "kernel_resource_kinds": sorted(pre["kernel_resource_kinds"]), "ir_schema": schema_snapshot(schema_text),
            "dispatch": dispatch, "engine_core_files": core, "eoo_ir_files": ir_core}
