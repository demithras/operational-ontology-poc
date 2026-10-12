"""Checks shared by the evaluator and the launcher guard (run_h29.py): oracle isolation (C29-0), FREEZE_G5 state and manifest completeness
(s9), dev size overrides / floors. One implementation so the evaluator and the launcher can never disagree (G3-E31b lesson)."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

ROUND3 = Path(__file__).resolve().parents[3]
FREEZE_G5 = ROUND3 / "protocol" / "FREEZE_G5.json"
FREEZE_G4 = ROUND3 / "protocol" / "FREEZE_G4.json"
CATALOGUE_REL = "src/r3_harness/h28/adapters.py"
ORACLE_ROOTS = ("continuity", "recoverymodel", "extoracle", "ops_model", "authority_v2", "view", "lowproj")
BANNED = ("paladin", "conventional", "r3_harness", "eoo_", "r3_shared.histstore", "r3_shared.variant")
WORLD_LOG_OK = ("recoverymodel",)        # Q11: world_log may be referenced by the replay model only

# s9 freeze manifest (ORACLE-AND-HARNESS-G5): every file named in an invalid_if clause or a frozen rule
MANIFEST_FILES = (
    "spec/protections/PROT-H29.md", "spec/gate5/PROTOCOL-P1g.md", "spec/gate5/ORACLE-AND-HARNESS-G5.md", "spec/gate5/EQUIVALENCE-G5.md",
    "spec/gate5/OPEN-QUESTIONS.md", "spec/gate5/dependency-graph.json", "spec/gate5/envelope-ops.json", "spec/gate5/reason-map.json",
    "protocol/AUTHOR_DECISIONS_2026-10-12.md", "threat_model/survivability_envelope.json", "threat_model/security_invariants.json",
    "schemas/dependency-graph.schema.json",
    "src/r3_harness/h29/faults.py", "src/r3_harness/h29/rules.py", "src/r3_harness/h29/adapters_h29.py", "src/r3_shared/faultplane.py",
    "src/r3_shared/authsvc.py", "src/r3_shared/authsvc_server.py", "src/r3_shared/host.py", "src/r3_harness/h28/adapters.py",
    "src/r3_oracle/continuity.py", "src/r3_oracle/recoverymodel.py", "src/r3_oracle/extoracle.py", "src/r3_oracle/ops_model.py",
    "src/r3_oracle/authority_v2.py", "src/r3_oracle/view.py", "src/r3_oracle/lowproj.py", "src/r3_harness/h29/evaluator.py")
HASH_CLAUSE_C = ("threat_model/survivability_envelope.json", "spec/gate5/envelope-ops.json", "spec/gate5/dependency-graph.json",
                 "src/r3_harness/h29/faults.py", "src/r3_harness/h29/rules.py")      # invalid_if (c)


def sha(rel: str) -> str:
    return hashlib.sha256((ROUND3 / rel).read_bytes()).hexdigest()


def manifest_paths() -> list:
    fam = sorted(str(p.relative_to(ROUND3)) for p in (ROUND3 / "spec/gate5/authority-versions").rglob("*.json"))
    return list(MANIFEST_FILES) + fam


def freeze_state(path: Path | None = None) -> tuple[dict, dict]:
    p = path or FREEZE_G5
    frozen = json.loads(p.read_text())["files"] if p.is_file() else {}
    return frozen, {f: sha(f) for f in frozen if (ROUND3 / f).is_file()}


def manifest_state(path: Path | None = None) -> dict:
    """{missing_from_freeze, missing_on_disk (files of the manifest that do not exist), freeze_paths_missing_on_disk}."""
    frozen, _ = freeze_state(path)
    want = manifest_paths()
    return {"missing_from_freeze": sorted(f for f in want if f not in frozen),
            "missing_on_disk": sorted(f for f in want if not (ROUND3 / f).is_file()),
            "freeze_paths_missing_on_disk": sorted(f for f in frozen if not (ROUND3 / f).is_file())}


def catalogue_state() -> tuple[str | None, str]:
    frozen = json.loads(FREEZE_G4.read_text())["files"] if FREEZE_G4.is_file() else {}
    return frozen.get(CATALOGUE_REL), sha(CATALOGUE_REL)


def oracle_isolation(src_dir: Path | None = None, roots=ORACLE_ROOTS) -> tuple[bool, list]:
    """C29-0: the import closure of the oracle roots imports no variant, no r3_harness, no HistoryStore; world_log only in recoverymodel."""
    seen, todo, bad = set(), list(roots), []
    base = src_dir or ROUND3 / "src" / "r3_oracle"
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        f = base / f"{name}.py"
        if not f.is_file():
            continue
        for n in ast.walk(ast.parse(f.read_text())):
            mods = [a.name for a in n.names] if isinstance(n, ast.Import) else (
                [("." * n.level) + (n.module or "")] + [("." * n.level) + (n.module or "") + "." + a.name for a in n.names]
                if isinstance(n, ast.ImportFrom) else [])
            for m in mods:
                if m.lstrip(".").startswith(BANNED):
                    bad.append(f"{name}: imports {m}")
                if m.startswith("r3_oracle."):
                    todo.append(m.split(".")[1])
                elif m.startswith(".") and not m.startswith(".."):
                    todo.append(m.lstrip(".").split(".")[0])
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value == "world_log" and name not in WORLD_LOG_OK:
                bad.append(f"{name}: references 'world_log'")
    return not bad, bad


# ---- floors (official) and the stamped dev scaling ---------------------------------------------------------------------
FLOORS = {"min_env": 5000, "min_ctrl": 600, "min_bnd_each": 50, "min_class_seqs": 450, "min_cp_seqs": 60, "min_during_fault": 300, "min_node": 300,
          "min_post": 300, "min_blocked": 100, "min_safe_during": 300, "min_fault_share_pct": 50}
SIZES = {"env": 5600, "ctrl": 600, "bnd": 200}
FACTOR = 0.5


def overrides_for(n_env: int, n_ctrl: int, n_bnd: int) -> dict:
    """Dev-size stamped overrides: every count floor scaled to the run size (x FACTOR), recorded in the manifest, refused on non-dev ids."""
    if n_env >= SIZES["env"] and n_ctrl >= SIZES["ctrl"] and n_bnd >= SIZES["bnd"]:
        return {}
    s = n_env / SIZES["env"]
    sc = lambda v: max(1, int(v * s * FACTOR))  # noqa: E731
    ov = {k: sc(FLOORS[k]) for k in ("min_class_seqs", "min_cp_seqs", "min_during_fault", "min_node", "min_post", "min_blocked", "min_safe_during")}
    ov.update(min_env=n_env, min_ctrl=n_ctrl, min_bnd_each=max(1, n_bnd // 8))
    return ov
