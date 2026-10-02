"""Seed of the Project Ontology built from REAL round2 artifacts, read-only.

File bytes come from ``git show HEAD:<path>`` (the committed blobs, never the working tree); commit metadata from
``git show -s`` / ``git log -1``. Nothing here writes to the repository.

What is read: protocol/FREEZE.json + thresholds.json, hypotheses/h15..h22/contract.json (claim, rivals, predictions,
falsifiers), experiments/h15/exp-h15-00{1,2}/*.json (evidence records), the H15 verdict.json files.
What is modelled (not read): the Component list, which components exist for which hypothesis, the principals.
"""
from __future__ import annotations

import json
import subprocess
from typing import Optional

from domains._support import canonical_json, sha256_hex
from .logic.freeze import ROUND2, BlobReader, git_blob_reader

EVIDENCE_SCHEMA = "schemas/evidence-record.schema.json"
H15_EVALUATOR = "src/eoo_h15/evaluate.py"
H15_EVIDENCE_FILES = ("real-domain-roundtrip.json", "generated-roundtrip.json", "ambiguity-corpus.json",
                      "sidecar-audit.json", "mutation-results.json", "compiler-diff-metrics.json")
H15_EXPERIMENTS = (("exp-h15-001", "1"), ("exp-h15-002", "2"))
# (id, path, hypotheses it exists for). src/eoo_<surface> of H15's candidate language is not modelled: tests/h15 bans
# that name from domains/. The legacy draft file is deliberately linked to nothing (a real orphan).
COMPONENTS = (("cmp-eoo-ir", "src/eoo_ir", ("H15", "H16", "H21")), ("cmp-eoo-h15", "src/eoo_h15", ("H15",)),
              ("cmp-eoo-dsl", "src/eoo_dsl", ("H15",)),
              ("cmp-eoo-engine", "src/eoo_engine", ("H16", "H17", "H20")), ("cmp-hdd", "src/hdd", ("H15", "H18")),
              ("cmp-legacy-draft", "history/legacy_round2_draft_hypotheses.md", ()))


def _git(*args: str) -> str:
    res = subprocess.run(["git", "-C", str(ROUND2), *args], capture_output=True, timeout=60)
    if res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {res.stderr.decode(errors='replace').strip()}")
    return res.stdout.decode().strip()


def commit_row(sha: str) -> dict:
    _sha, msg, when = _git("show", "-s", "--format=%H%x1f%s%x1f%cI", sha).split("\x1f")
    return {"op": "create", "type": "Commit", "key": _sha, "props": {"sha": _sha, "message": msg, "committed_at": when}}


def last_commit(path: str) -> str:
    return _git("log", "-1", "--format=%H", "HEAD", "--", path)


def _c(typ: str, key, **props) -> dict:
    return {"op": "create", "type": typ, "key": key, "props": {k: v for k, v in props.items() if v is not None}}


def _l(typ: str, src: tuple, dst: tuple) -> dict:
    return {"op": "link", "type": typ, "src": list(src), "dst": list(dst), "props": {}}


def principals() -> list:
    return [{"pid": "researcher-1", "roles": ["researcher"], "relations": [], "delegated_by": None},
            {"pid": "researcher-2", "roles": ["researcher"], "relations": [], "delegated_by": None},
            {"pid": "viewer-1", "roles": [], "relations": [], "delegated_by": None}]


def build_seed(reader: Optional[BlobReader] = None, *, h15_state: str = "EVALUATED") -> dict:
    """``h15_state``: ``EVALUATED`` (as committed: both experiments attached, verdict stored) or ``RUNNING`` (a replay
    starting point: experiment exp-h15-002's six evidence artifacts exist but are not attached, no verdict)."""
    assert h15_state in ("EVALUATED", "RUNNING")
    rd = reader or git_blob_reader()
    fz = json.loads(rd("protocol/FREEZE.json"))
    protocol = fz["protocol_sha256"]
    file_sha = {f["path"]: f["sha256"] for f in fz["files"]}
    thresholds = json.loads(rd("protocol/thresholds.json"))
    head = _git("show", "-s", "--format=%H", "HEAD")
    commits: dict = {head: commit_row(head)}
    objs: list = []
    links: list = []

    def need_commit(sha: str) -> str:
        if sha not in commits:
            commits[sha] = commit_row(sha)
        return sha

    contracts = sorted(p for p in file_sha if p.startswith("hypotheses/") and p.endswith("/contract.json"))
    for path in contracts:
        c = json.loads(rd(path))
        hid, hn = c["id"], c["id"].lower()
        phase = h15_state if hid == "H15" else "PREREGISTERED"
        objs.append(_c("Hypothesis", hid, id=hid, claim=c["claim"], phase=phase, freeze_hash=protocol))
        for kind, typ, link, field in (("rival", "Rival", "HAS_RIVAL", "rivals"),
                                       ("prediction", "Prediction", "PREDICTS", "predictions"),
                                       ("falsifier", "Falsifier", "FALSIFIED_BY", "falsifiers")):
            for i, text in enumerate(c[field], 1):
                rid = f"{hid}-{kind}-{i}"
                objs.append(_c(typ, rid, id=rid, statement=text))
                links.append(_l(link, ("Hypothesis", hid), (typ, rid)))
        cv = f"cv-{hid}"
        objs.append(_c("ContractVersion", cv, id=cv, sha256=file_sha[path], git_commit=need_commit(last_commit(path)),
                       frozen_at=fz["frozen_at"]))
        exps = H15_EXPERIMENTS if hid == "H15" else ((f"exp-{hn}-001", "1"),)
        for eid, ver in exps:
            ref = H15_EVALUATOR if hid == "H15" else f"{path}#evaluator"
            objs.append(_c("Experiment", eid, id=eid, version=ver, evidence_schema_ref=EVIDENCE_SCHEMA, evaluator_ref=ref))
            links.append(_l("TESTED_BY", ("Hypothesis", hid), ("Experiment", eid)))
            for name, value in (thresholds.get(hid) or {}).items():
                mid = f"{hid}.{name}"
                if not any(o["type"] == "Metric" and o["key"] == mid for o in objs):
                    objs.append(_c("Metric", mid, id=mid, name=name))
                    objs.append(_c("Threshold", mid, id=mid, value=value))
                    links.append(_l("GOVERNED_BY", ("Metric", mid), ("Threshold", mid)))
                links.append(_l("MEASURES", ("Experiment", eid), ("Metric", mid)))
    _h15_evidence(rd, objs, links, need_commit, h15_state)
    for cid, path, hyps in COMPONENTS:
        rd(path)  # fails loudly if a modelled component path is not in the committed tree
        objs.append(_c("Component", cid, id=cid, path=path, orphan_flagged=False))
        links += [_l("EXISTS_FOR", ("Component", cid), ("Hypothesis", h)) for h in hyps]
    side = json.loads(rd("hypotheses/h15/contract.json"))["experiment"]["sidecar_classification"]["decision"]
    objs.append(_c("Decision", "dec-h15-sidecar-option1", id="dec-h15-sidecar-option1", rationale=side))
    ops = [_c("Commit", k, **v["props"]) for k, v in commits.items()] + objs + links
    return {"description": f"Project Ontology seed read from the committed repo at {head[:10]} (H15 {h15_state})",
            "head_commit": head, "protocol_freeze_hash": protocol, "principals": principals(), "ops": ops}


def _h15_evidence(rd, objs: list, links: list, need_commit, h15_state: str) -> None:
    for exp, ver in H15_EXPERIMENTS:
        attached = not (h15_state == "RUNNING" and exp == "exp-h15-002")
        for name in H15_EVIDENCE_FILES:
            path = f"experiments/h15/{exp}/{name}"
            rec = json.loads(rd(path))
            eid = f"{exp}/{name}"
            commit = need_commit(rec["git_commit"])
            objs.append(_c("Evidence", eid, id=eid, payload_hash=rec["payload_hash"], git_commit=commit,
                           experiment_version=ver, environment=canonical_json(rec["environment"])))
            if attached:
                links.append(_l("PRODUCES", ("Experiment", exp), ("Evidence", eid)))
            links.append(_l("SUPPORTS_OR_REFUTES", ("Evidence", eid), ("Hypothesis", "H15")))
            links.append(_l("CAPTURED_AT", ("Evidence", eid), ("Commit", commit)))
    if h15_state == "EVALUATED":
        vpath = "experiments/h15/exp-h15-002/verdict.json"
        v = json.loads(rd(vpath))
        reason = f"machine-derived by eoo_h15.evaluate over exp-h15-002 (committed verdict.json: {v['verdict']})"
        objs.append(_c("Verdict", "verdict-H15-1", id="verdict-H15-1", value=v["verdict"], reason=reason,
                       derivation_hash=sha256_hex(rd(vpath).decode()), git_commit=need_commit(
                           last_commit(vpath))))
        links.append(_l("EVALUATES", ("Verdict", "verdict-H15-1"), ("Hypothesis", "H15")))
