"""Paired-world noninterference helpers (PROT-H26): two worlds equal on everything the observer may know, differing in a
protected fact, must give byte-identical canonical observations on every low channel."""
from __future__ import annotations

import json

from g3_rig import G3Rig

TYPES = ["Hypothesis", "Rival", "Prediction", "Falsifier", "Experiment", "Metric", "Threshold", "Evidence", "Verdict",
         "Component", "ContractVersion", "Commit", "Test", "Decision", "Failure"]
LINKS = ["HAS_RIVAL", "TESTED_BY", "MEASURES", "GOVERNED_BY", "PRODUCES", "SUPPORTS_OR_REFUTES", "DETECTED_BY", "VALIDATES"]
REFS = ["Hypothesis:H-A", "Hypothesis:NOPE", "Experiment:E-A@v1", "Evidence:EV-C1", "Component:cmp-live", "Failure:f-1",
        "Rival:R-A", "Threshold:T-A", "Verdict:verdict-H-D-1", "Failure:cv-x1", "Failure:cv-x2", "Decision:DEC-1"]


def canon(res) -> str:
    return json.dumps([res.status, res.body], sort_keys=True)


def battery(r: G3Rig, who: str, sid: str | None, extra=()) -> list:
    """Every low channel, in a fixed order, on visible / hidden / absent refs. Returns [(label, canonical)]."""
    d, tk, out = r.dep, r.tok(who), []
    out.append(("tools", json.dumps(sorted([t.name, t.input_schema] for t in d.tools(tk)), sort_keys=True, default=str)))
    for ref in REFS:
        out.append((f"read:{ref}", canon(d.read_object(tk, ref))))
        out.append((f"prov_object:{ref}", canon(d.prov_object(tk, ref))))
        for lt in LINKS[:4]:
            out.append((f"links:{ref}:{lt}", canon(d.list_links(tk, ref, lt))))
    for t in TYPES + ["NoSuchType"]:
        out.append((f"list:{t}", canon(d.list_objects(tk, t))))
    for name, args in (("evidence_count", {"hypothesis": "H-C"}), ("evidence_count", {"hypothesis": "H-A"}),
                       ("find_orphan_components", {}), ("evidence_count", {"hypothesis": "H-NOPE"}), ("nope", {})):
        out.append((f"query:{name}:{args}", canon(d.query(tk, name, args))))
    out.append(("read-get", canon(d.read(tk, "get", {"type": "Experiment", "key": "E-A@v1"}))))
    for i, (op, args) in enumerate((("start_run", {"hypothesis": "H-A"}), ("attach_evidence", {"hypothesis": "H-C", "evidence": "EV-C1"}),
                                    ("record_decision", {"decision": "DEC-1", "contract_version": "CV-1"}),
                                    ("edit_threshold", {"threshold": "T-A", "value": {"min": 3}}))):
        out.append((f"direct:{op}", canon(d.direct(tk, op, args, request_id=f"b-{who}-{i}"))))
        out.append((f"tool:{op}", canon(d.call_tool(tk, op, args, request_id=f"c-{who}-{i}"))))
    out.append(("revoke-hidden", canon(d.revoke(tk, "e-hidden", "b-rv"))))
    out.append(("delegate-hidden-parent", canon(d.delegate(tk, {"id": "n1", "issuer": who, "child": "agent-draft-1", "parent": "e-hidden",
                "scope": {"operations": ["start_run"], "resources": [{"type": "Hypothesis", "keys": None}]}, "expires_at": None,
                "redelegable": False, "issued_at": 0}, "b-dl"))))
    for kind in ("judge", "appeal", "execute"):
        a = {"kind": kind, "case": "hidden-case"}
        if kind == "judge":
            a |= {"stage": "decision", "value": "concur", "merit": "m"}
        out.append((f"const:{kind}", canon(d.constitutional(tk, a, f"b-c-{kind}"))))
    for did in ("nope", "approve:00000001", "b-0"):
        out.append((f"prov_decision:{did}", canon(d.prov_decision(tk, did))))
        out.append((f"used_as:{did}", canon(d.authority_used_as(tk, did))))
    for label, fn in extra:
        out.append((label, canon(fn(r, tk))))
    if sid is not None:
        out.append(("poll", canon(d.poll(tk, sid))))
        out.append(("poll-again", canon(d.poll(tk, sid))))
    return out


def run_pair(tmp, hidden, who="viewer-1", subscribe=True, extra=(), mutants=(), **kw):
    """Build worlds k=0 and k=1 that differ only through hidden(rig, k); return the two batteries."""
    outs = []
    for k in (0, 1):
        r = G3Rig(tmp, v3=True, mutants=mutants, **kw)
        sid = None
        if subscribe:
            sid = r.dep.subscribe(r.tok(who), {"types": TYPES}).body["sub"]
        hidden(r, k)
        outs.append(battery(r, who, sid, extra))
    return outs


def divergences(pair) -> list:
    return [a[0] for a, b in zip(*pair) if a != b]
