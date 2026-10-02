"""Case fixtures: pure edits of the real Project seed (a list of store ops) for one generated lifecycle case."""
from __future__ import annotations

import copy
import hashlib

from .evaluators import GEN as GEN_EVALUATOR
HYPS = ("H15", "H16", "H17", "H18", "H19", "H20", "H21", "H22")
SUBJECTS = HYPS[1:]


def facts_for(base_ops: list, subject: str, commit: str) -> dict:
    thr = sorted(o["key"] for o in base_ops if o["op"] == "create" and o["type"] == "Threshold" and str(o["key"]).startswith(subject + "."))
    tv = next(o["props"]["value"] for o in base_ops if o["op"] == "create" and o["type"] == "Threshold" and o["key"] == thr[0])
    comps: dict = {}
    for o in base_ops:
        if o["op"] == "link" and o["type"] == "EXISTS_FOR":
            comps.setdefault(o["src"][1], []).append(o["dst"][1])
    comps = {o["key"]: comps.get(o["key"], []) for o in base_ops if o["op"] == "create" and o["type"] == "Component"}
    other = HYPS[(HYPS.index(subject) + 1) % len(HYPS)]
    return {"exp": f"exp-{subject.lower()}-001", "threshold": thr[0], "threshold_value": tv, "cv": f"cv-{subject}", "other": other,
            "components": comps, "commit": commit}


def evidence_props(ev: dict, commit: str) -> dict:
    h = ev["tag"] + hashlib.sha256(ev["id"].encode()).hexdigest()[:15]
    p = {"id": ev["id"], "payload_hash": h, "git_commit": commit, "experiment_version": "1", "environment": '{"gen":1}'}
    bad = {"version": ("experiment_version", "99"), "env": ("environment", ""), "commit": ("git_commit", ""), "hash": ("payload_hash", "")}
    if ev["pin"] in bad:
        p[bad[ev["pin"]][0]] = bad[ev["pin"]][1]
    return p


def case_ops(base_ops: list, case: dict) -> list:
    """The seed ops of ``case``: the real seed with the subject hypothesis reshaped and the case fixtures added."""
    ops, s, f = copy.deepcopy(base_ops), case["subject"], case["facts"]
    for o in ops:
        if o["op"] == "create" and o["type"] == "Hypothesis" and o["key"] == s:
            o["props"]["phase"] = case["phase0"]
            if case["phase0"] == "DRAFT":
                o["props"].pop("freeze_hash", None)
            else:
                o["props"]["freeze_hash"] = "fh-seed"
        if o["op"] == "create" and o["type"] == "Experiment" and o["key"] == f["exp"]:
            o["props"]["evaluator_ref"] = GEN_EVALUATOR if case["complete"]["evaluator"] else ""
    drop = {"rival": "HAS_RIVAL", "prediction": "PREDICTS", "falsifier": "FALSIFIED_BY"}
    gone = {drop[k] for k in drop if not case["complete"][k]}
    ops = [o for o in ops if not (o["op"] == "link" and o["type"] in gone and o["src"][1] == s)]
    for ev in case["evidence"]:
        ops.append({"op": "create", "type": "Evidence", "key": ev["id"], "props": evidence_props(ev, f["commit"])})
    if case.get("decision"):
        d = case["decision"]
        ops.append({"op": "create", "type": "Decision", "key": d["id"], "props": {"id": d["id"], "rationale": d["rationale"]}})
    for c in case["components"]:
        ops.append({"op": "create", "type": "Component", "key": c["id"], "props": {"id": c["id"], "path": "gen/" + c["id"], "orphan_flagged": False}})
        ops.append({"op": "link", "type": "EXISTS_FOR", "src": ["Component", c["id"]], "dst": ["Hypothesis", s], "props": {}})
    return ops
