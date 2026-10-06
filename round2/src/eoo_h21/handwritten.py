"""handwritten-diff: add the preregistered ordinary resources to a COPY of the project IR, regenerate, count handwritten code."""
from __future__ import annotations

import ast
import hashlib
import re
import tempfile
from pathlib import Path

from eoo_exp.util import ROOT, git, sha_file
from eoo_toolchain import build, load_generated
from eoo_toolchain.runtime import EngineClient, UnknownTool

from . import conformance, differential, cases, engine_check, replication

TOKENS = ("Replication", "REPLICATES", "register_replication", "count_replications")
ENDPOINT = re.compile(r"^(get|list|query|follow|call|act)_|^(Fn|Act)_|^AgentSurface$")


def source_hashes(sub: str) -> dict:
    return {p.relative_to(ROOT).as_posix(): sha_file(p) for p in sorted((ROOT / sub).rglob("*.py")) if "__pycache__" not in p.parts}


def endpoint_definitions(src: str, tokens=TOKENS) -> list:
    """Function / class definitions in handwritten source that look like endpoint/tool code for a new resource."""
    out = []
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and ENDPOINT.search(n.name) and any(t.lower() in n.name.lower() for t in tokens):
            out.append(n.name)
    return sorted(out)


def logic_loc(path: Path, names: tuple) -> dict:
    src = path.read_text()
    lines = src.splitlines()
    per = {}
    for n in ast.parse(src).body:
        if isinstance(n, ast.FunctionDef) and n.name in names:
            body = [ln for ln in lines[n.lineno - 1:n.end_lineno] if ln.strip() and not ln.strip().startswith(("#", '"""'))]
            per[n.name] = len(body)
    return per


def token_files() -> dict:
    hits = {}
    for base in ("src/eoo_toolchain", "domains"):
        for p in sorted((ROOT / base).rglob("*.py")):
            t = p.read_text()
            h = [x for x in TOKENS if x in t]
            if h:
                hits[p.relative_to(ROOT).as_posix()] = h
    return hits


def demo(ir2: dict, surf_mod) -> dict:
    """Use the new resources through the GENERATED surface on the unchanged Engine over a real temporary Git repository."""
    from domains.project.logic.freeze import git_blob_reader
    from eoo_h18.rig import EooRig
    rig = EooRig(reader=git_blob_reader(), package=ir2, extend=replication.extend)
    ref, rows = "refs/heads/main", []
    types = [o["id"] for o in ir2["object_types"]]

    def surface(engine, pid):
        c = EngineClient(engine)
        return c, surf_mod.AgentSurface(c, c.principal_plain(pid), c.world(types), engine_check.real_opaque(engine))
    e = rig.engine(ref)
    c, s = surface(e, "researcher-1")
    rec = s.call("act_register_replication", idempotency_key="h21-r1", id="rep-1", experiment_ref="exp-h15-002", outcome="reproduced")
    rows.append({"step": "researcher registers a replication of an EVALUATED experiment via the generated tool", "state": rec["state"],
                 "tool_present": True, "expected": "RECONCILED_SUCCESS", "ok": rec["state"] == "RECONCILED_SUCCESS"})
    rec2 = s.call("act_register_replication", idempotency_key="h21-r2", id="rep-2", experiment_ref="exp-h16-001", outcome="reproduced")
    gates = [g["gate"] for g in rec2["gates"] if not g["passed"]]
    rows.append({"step": "same tool, experiment not EVALUATED", "state": rec2["state"], "denied_gate": gates[0] if gates else None,
                 "expected": "DENIED at preconditions", "ok": rec2["state"] == "DENIED" and gates[:1] == ["preconditions"]})
    cv, sv = surface(rig.engine(ref), "viewer-1")
    try:
        sv.call("act_register_replication", idempotency_key="h21-v", id="rep-3", experiment_ref="exp-h15-002", outcome="x")
        absent = False
    except UnknownTool:
        absent = True
    rows.append({"step": "viewer-1 has no register_replication tool (absent, not refused)", "tool_present": "act_register_replication" in sv.tools,
                 "expected": "UnknownTool", "ok": absent and "act_register_replication" not in sv.tools})
    e3 = rig.engine(ref)
    c3, s3 = surface(e3, "researcher-1")
    n1, n2 = s3.call("call_count_replications", experiment="exp-h15-002"), s3.call("call_count_replications", experiment="exp-h16-001")
    rows.append({"step": "count_replications through the generated function tool on a freshly projected Engine", "count_exp_h15_002": n1,
                 "count_exp_h16_001": n2, "expected": "1 and 0", "ok": (n1, n2) == (1, 0)})
    objs = s3.call("query_VersionedResearchObject")
    got = sorted({type(o).__name__ for o in objs})
    rows.append({"step": "generic interface tool returns the new Replication object (7th implementer, no generator change)",
                 "types": got, "replications_returned": sum(type(o).__name__ == "Replication" for o in objs), "expected": "Replication among 7 types",
                 "ok": "Replication" in got and len(got) == 7})
    return {"steps": rows, "all_ok": all(r["ok"] for r in rows), "git_repo": "temporary repository (GitStore); commits are real"}


def payload(seed: int, n_cases: int = 1500) -> dict:
    tc0 = source_hashes("src/eoo_toolchain")
    gate0 = {p: {"sha256_now": sha_file(ROOT / p), "sha256_HEAD": hashlib.sha256(git("show", f"HEAD:round2/{p}").encode()).hexdigest()}
             for p in ("domains/project/ir.json", "domains/project/ir.v2.json")}
    from domains._pack import load_ir
    base_ir, ir2 = load_ir("project"), replication.extended_ir()
    d0, d1 = tempfile.mkdtemp(prefix="h21-before-"), tempfile.mkdtemp(prefix="h21-after-")
    i0, i1 = build(base_ir, d0), build(ir2, d1)
    sdk0, _c0, surf0 = load_generated(d0, i0["package"])
    sdk1, _c1, surf1 = load_generated(d1, i1["package"])
    added_tools = sorted(set(i1["tools"]) - set(i0["tools"]))
    added_classes = sorted(n for n in dir(sdk1) if n not in dir(sdk0) and not n.startswith("_"))
    scan = {}
    for p in sorted((ROOT / "src/eoo_h21").glob("replication.py")):
        scan[p.relative_to(ROOT).as_posix()] = endpoint_definitions(p.read_text())
    planted = "def act_register_replication(client, pid, **kw):\n    return client.propose('register_replication', kw, pid)\n"
    conf = conformance.check(ir2, sdk1)
    cs = cases.unique_cases(ir2, n_cases, seed + 11)
    diff = differential.run(ir2, surf1, cs, sample_rows=3)
    tc1 = source_hashes("src/eoo_toolchain")
    logic = logic_loc(ROOT / "src/eoo_h21/replication.py", ("_count", "_experiment_evaluated", "_link_payload", "_outcome", "extend"))
    return {
        "ir_gate0_unchanged": gate0, "gate0_files_unchanged": all(v["sha256_now"] == v["sha256_HEAD"] for v in gate0.values()),
        "extended_ir": "copy built in memory by eoo_h21.replication.extended_ir() (Gate-0 file untouched)",
        "preregistered_resources": ["object type Replication", "link REPLICATES", "action register_replication", "function count_replications"],
        "declarative_additions": {"object_types": ["Replication"], "link_types": ["REPLICATES"], "functions": ["count_replications"],
                                  "actions": ["register_replication"], "authority_rules": ["researcher-register-replication"]},
        "generated_before": {"files": i0["files"], "tools": len(i0["tools"])}, "generated_after": {"files": i1["files"], "tools": len(i1["tools"])},
        "generated_new_tools": added_tools, "generated_new_sdk_symbols": added_classes,
        "toolchain_files_before": tc0, "toolchain_files_after": tc1, "toolchain_files_changed": sorted(k for k in tc0 if tc0[k] != tc1.get(k)) + sorted(set(tc1) - set(tc0)),
        "token_occurrences_in_toolchain_and_domains": token_files(),
        "read_only_paths_dirty": git("status", "--porcelain", "--", "round2/domains", "round2/src/eoo_engine", "round2/src/eoo_engine_git",
                                     "round2/src/eoo_ir", "round2/protocol", "round2/hypotheses").splitlines(),
        "handwritten_endpoint_definitions": {"scanned_files": scan, "count": sum(len(v) for v in scan.values()),
                                             "scanner_known_negative_planted_endpoint": endpoint_definitions(planted)},
        "handwritten_endpoint_or_tool_code_added": sum(len(v) for v in scan.values()) + len(token_files()),
        "domain_logic": {"bindings": 4, "bound": ["function fn:count_replications:v1", "precondition 'experiment is EVALUATED'",
                                                  "payload register_replication#1", "outcome_predicate (replication + REPLICATES in Git)"],
                         "lines_per_function": logic, "lines_total": sum(logic.values()), "file": "src/eoo_h21/replication.py",
                         "counted_separately": "domain logic is not endpoint/tool code; reported, not a support condition"},
        "regenerated_conformance": {k: conf[k] for k in ("checks", "passed", "failed", "conformance", "failures")},
        "regenerated_differential": {k: diff[k] for k in ("cases", "mismatching_cases", "overexposed_total", "underexposed_total")},
        "end_to_end": demo(ir2, surf1),
    }
