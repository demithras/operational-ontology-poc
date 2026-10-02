"""Mutation proof: edits applied to a TEMP COPY of the tree (never to the repository), then every detector is run on it.

Engine mutants insert domain-keyed behaviour in the Engine; adapter mutants move a governance check into an adapter. Each
mutant is judged by independent signals: the token scan, the identity-in-branch scan, the adapter audit, the alias-invariance
probe (subprocess against the mutated tree) and the ok-mode adapter probe. Controls: the unmutated copy and a no-op edit.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from eoo_exp.util import ROOT

from . import adapter_dynamic, adapter_static, static_audit

SKIP = shutil.ignore_patterns(".venv", "__pycache__", "experiments", "tests", ".git", "*.egg-info", ".pytest_cache", "history", "baselines")
M, P = "manufacturing-ontology", "project-ontology"

ENGINE = [  # id, description, file, old, new
    ("E1_package_id_literal_branch", "if package_id == <real domain package id>: skip the policy gate", "src/eoo_engine/gates.py",
     "    results, errors, classified = [], [], []\n",
     f"    if eng.model.package_id == {M!r}:\n        return 'APPROVED', gate('policy', True, {{}})\n    results, errors, classified = [], [], []\n"),
    ("E2_action_id_branch", "authority gate skipped for one named action", "src/eoo_engine/pipeline.py",
     "    if not dec.allowed:\n", "    if not dec.allowed and spec.rid != 'transfer_inventory':\n"),
    ("E3_identity_prefix_branch", "package_id.startswith(<fragment>): skip the policy gate (no domain token in the source)",
     "src/eoo_engine/gates.py", "    results, errors, classified = [], [], []\n",
     "    if eng.model.package_id.startswith('manuf'):\n        return 'APPROVED', gate('policy', True, {})\n    results, errors, classified = [], [], []\n"),
    ("E4_object_type_branch", "hard constraints ignored for effects on one named object type", "src/eoo_engine/pipeline.py",
     "    if hard_fail:\n", "    if hard_fail and not any(e.target == 'Hypothesis' for e in spec.effects):\n"),
]
ADAPTER = [
    ("A1_policy_in_wms_adapter", "WMS adapter evaluates a quantity policy before accepting an approved transfer",
     "domains/manufacturing/adapters/wms_fake.py", "        xid = effect[\"execution\"]\n",
     "        xid = effect[\"execution\"]\n        if not self._policy_allows(payload):\n            raise WmsUnavailable('policy: quantity above the limit')\n",
     "    def _policy_allows(self, payload):\n        return payload['quantity'] <= 50\n\n", "    # -- fake internals", "WmsFake", "manufacturing"),
    ("A1b_unnamed_policy_in_wms_adapter", "same behaviour as A1 under an innocuous name (the vocabulary audit cannot see it)",
     "domains/manufacturing/adapters/wms_fake.py", "        xid = effect[\"execution\"]\n",
     "        xid = effect[\"execution\"]\n        if not self._within(payload):\n            raise WmsUnavailable('limit reached')\n",
     "    def _within(self, payload):\n        return payload['quantity'] <= 50\n\n", "    # -- fake internals", "WmsFake", "manufacturing"),
    ("A2_authority_in_git_adapter", "Git adapter refuses effects an authority rule would not allow", "domains/project/adapters/git_fake.py",
     "        eid = effect[\"effect_id\"]\n", "        eid = effect[\"effect_id\"]\n        if not self._authorized(effect):\n            raise GitUnavailable('not authorized')\n",
     "    def _authorized(self, effect):\n        return not effect['effect_id'].endswith('/e0')\n\n", "    def observations", "GitFake", "project"),
    ("A3_precondition_in_engine_git_adapter", "Git-backed adapter checks a precondition of the action", "src/eoo_engine_git/adapter.py",
     "        eid, ex = effect[\"effect_id\"], effect[\"execution\"]\n",
     "        eid, ex = effect[\"effect_id\"], effect[\"execution\"]\n        if not self._precondition_holds(pay_of(payload)):\n            raise BatchError('precondition failed')\n",
     "    def _precondition_holds(self, p):\n        return bool(p)\n\n", "    def observations", "GitAdapter", None),
]


def _copy_tree(dst: Path) -> Path:
    shutil.copytree(ROOT, dst / "round2", ignore=SKIP)
    return dst / "round2"


def _edit(path: Path, old: str, new: str) -> None:
    s = path.read_text()
    assert s.count(old) == 1, f"{path}: anchor {old[:50]!r} found {s.count(old)} times"
    path.write_text(s.replace(old, new))


def _probe(tree: Path, n: int) -> dict:
    env = {**os.environ, "PYTHONPATH": f"{tree / 'src'}:{tree}", "PYTHONDONTWRITEBYTECODE": "1"}
    r = subprocess.run([sys.executable, "-m", "eoo_h20.mutant_probe", str(n)], env=env, cwd=tree, capture_output=True, text=True, timeout=900)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("PROBE ")]
    if r.returncode != 0 or not lines:
        raise RuntimeError("probe failed: " + r.stderr[-400:])
    out = json.loads(lines[-1][6:])
    assert str(tree) in out["engine_file"], "the probe imported the Engine from the wrong tree"
    return out


def engine_signals(tree: Path, n_probe: int) -> dict:
    a = static_audit.audit(tree, tree / "src")
    pr = _probe(tree, n_probe)
    return {"token_hits": a["token_branch_hits"] + a["token_literal_hits"], "identity_branch_hits": len(a["identity_branch_hits"]),
            "static_flagged": a["forbidden_core_branches"] + a["forbidden_core_literals"] > 0,
            "first_static_hit": (a["token_hits"] or a["identity_branch_hits"] or [None])[0],
            "alias_disagreements": pr["disagreements"], "alias_definitions": pr["definitions"],
            "dynamic_flagged": pr["disagreements"] > 0, "alias_example": (pr["examples"] or [None])[0]}


def _adapter_class(src: str, name: str):
    ns: dict = {"__name__": "h20_mutant_adapter"}
    exec(compile(src, "<mutant>", "exec"), ns)  # noqa: S102 - the mutated adapter source is the object under test
    return ns[name]


def adapter_signals(rel: str, mutated: str | None, cls: str | None, dom: str | None) -> dict:
    st = adapter_static.audit(overrides={rel: mutated} if mutated is not None else None)
    dyn = {"ran": False}
    if cls and dom and mutated is not None:
        rows = adapter_dynamic.ok_mode_probe({dom: _adapter_class(mutated, cls)})
        bad = [r for r in rows if r["domain"] == dom and not r["carried_out"]]
        dyn = {"ran": True, "ok_mode_refusals": len(bad), "example": bad[0] if bad else None}
    return {"static_violations": st["violations"], "static_flagged": st["violations"] > 0,
            "static_first": next((v for r in st["files"] for v in r["violations"]), None),
            "dynamic": dyn, "dynamic_flagged": bool(dyn.get("ok_mode_refusals"))}


def run_all(n_probe: int = 120) -> dict:
    rows = []
    with tempfile.TemporaryDirectory(prefix="h20-mut-") as tmp:
        base = _copy_tree(Path(tmp))
        control = engine_signals(base, n_probe)  # clean copy
        _edit(base / "src/eoo_engine/pipeline.py", "def _deny(eng, rec, g: dict) -> dict:\n", "def _deny(eng, rec, g: dict) -> dict:  # noop edit\n")
        noop = engine_signals(base, n_probe)
        shutil.rmtree(base)
        for mid, desc, rel, old, new in ENGINE:
            tree = _copy_tree(Path(tmp))
            _edit(tree / rel, old, new)
            sig = engine_signals(tree, n_probe)
            shutil.rmtree(tree)
            rows.append({"id": mid, "class": "domain_branch_in_engine", "description": desc, "file": rel, "target": True,
                         "signals": sig, "detected": sig["static_flagged"] or sig["dynamic_flagged"],
                         "detected_by": [k for k, v in (("static_token_or_identity_scan", sig["static_flagged"]),
                                                       ("alias_invariance_probe", sig["dynamic_flagged"])) if v]})
    ctrl_adapter = adapter_signals("domains/manufacturing/adapters/wms_fake.py", None, None, None)
    ctrl_dyn = adapter_dynamic.ok_mode_probe()
    for mid, desc, rel, old, new, meth, meth_before, cls, dom in ADAPTER:
        src = (ROOT / rel).read_text()
        assert src.count(old) == 1 and src.count(meth_before) >= 1, mid
        mutated = src.replace(old, new).replace(meth_before, meth + meth_before, 1)
        if mid.startswith("A3"):  # engine-git adapter: pay_of is the already-converted payload
            mutated = mutated.replace("pay_of(payload)", "to_plain(payload)")
        compile(mutated, rel, "exec")
        sig = adapter_signals(rel, mutated, cls, dom)
        rows.append({"id": mid, "class": "governance_in_adapter", "description": desc, "file": rel,
                     "target": True, "static_blind_spot": not sig["static_flagged"], "signals": sig, "detected": sig["static_flagged"] or sig["dynamic_flagged"],
                     "detected_by": [k for k, v in (("adapter_static_audit", sig["static_flagged"]),
                                                   ("ok_mode_adapter_probe", sig["dynamic_flagged"])) if v]})
    return {"controls": {"clean_copy": control, "noop_edit": noop, "adapter_static_clean": ctrl_adapter["static_violations"] == 0,
                         "ok_mode_probe_clean": all(r["carried_out"] for r in ctrl_dyn),
                         "clean": not control["static_flagged"] and not control["dynamic_flagged"] and not noop["static_flagged"]
                                  and not noop["dynamic_flagged"] and ctrl_adapter["static_violations"] == 0
                                  and all(r["carried_out"] for r in ctrl_dyn)},
            "mutants": rows}
