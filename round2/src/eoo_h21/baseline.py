"""Contextual baseline: generic OpenAPI generation over the same IR (treated as a conventional schema) plus the
hand-written authorization glue such a service needs per domain. Reported, never a support condition."""
from __future__ import annotations

import inspect

from eoo_toolchain.naming import ident

from . import cases, differential

JSON_T = {"string": "string", "integer": "integer", "number": "number", "boolean": "boolean", "json": "object"}


def _schema(te) -> dict:
    if isinstance(te, str):
        return {"type": JSON_T.get(te, "string")}
    (c, inner), = te.items()
    return {"type": "array", "items": _schema(inner)} if c == "list" else ({"type": "string"} if c == "ref" else _schema(inner))


def openapi(ir: dict) -> dict:
    """Generic REST/OpenAPI 3 document: schemas for object types, list/get paths, one POST per action, GET per function."""
    paths, schemas = {}, {}
    for o in ir["object_types"]:
        schemas[o["id"]] = {"type": "object", "properties": {p["name"]: _schema(p["type"]) for p in o["properties"]},
                            "required": [p["name"] for p in o["properties"] if p.get("required")]}
        paths[f"/{o['id']}"] = {"get": {"operationId": f"list_{o['id']}"}}
        paths[f"/{o['id']}/{{key}}"] = {"get": {"operationId": f"get_{o['id']}"}}
    for a in ir["actions"]:
        paths[f"/actions/{a['id']}"] = {"post": {"operationId": a["id"], "requestBody": {"content": {"application/json": {"schema": {
            "type": "object", "properties": {p["name"]: _schema(p["type"]) for p in a["inputs"]}}}}}}}
    for f in ir["functions"]:
        paths[f"/functions/{f['id']}"] = {"get": {"operationId": f["id"]}}
    return {"openapi": "3.0.3", "info": {"title": ir["package_id"], "version": ir["version"]}, "paths": paths, "components": {"schemas": schemas}}


# ---- hand-written authorization glue (what an OpenAPI service would add per domain) --------------------------------------
def _held(p: dict, rel: str, keys: list) -> bool:
    mine = {(t, k) for t, k, r in p["relations"] if r == rel}
    return bool(keys) and all(("Warehouse", k) in mine for k in keys)


def mfg_allowed(p: dict, action: str, warehouses: list) -> bool:
    if action != "transfer_inventory":
        return False
    direct = _held(p, "planner", warehouses) or _held(p, "junior_planner", warehouses)
    if p["delegated_by"] is None:
        return direct or _held(p, "agent_grant", warehouses)
    return _held(p, "agent_grant", warehouses) and mfg_allowed(p["delegated_by"], action, warehouses)


PROJECT_ACTION_ROLE = {"create_hypothesis": "researcher", "edit_threshold": "researcher", "preregister_hypothesis": "researcher",
                       "new_experiment_version": "researcher", "start_run": "researcher", "attach_evidence": "researcher",
                       "evaluate_hypothesis": "researcher", "supersede_hypothesis": "researcher", "record_decision": "researcher",
                       "flag_orphan_component": "researcher"}


def project_allowed(p: dict, action: str, _w: list) -> bool:
    return p["delegated_by"] is None and PROJECT_ACTION_ROLE.get(action) in p["roles"]


def loc(*names) -> int:
    """Non-blank, non-comment source lines of the named top-level definitions / assignments of this module."""
    import ast
    src = inspect.getsource(__import__(__name__, fromlist=["x"]))
    n = 0
    for node in ast.parse(src).body:
        nm = node.name if isinstance(node, ast.FunctionDef) else (node.targets[0].id if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) else None)
        if nm in names:
            n += sum(1 for ln in ast.get_source_segment(src, node).splitlines() if ln.strip() and not ln.strip().startswith("#"))
    return n


def agreement(domain: str, ir: dict, case_list: list) -> dict:
    ref = differential.load_oracle_module("authority_oracle").Reference(ir)
    glue = mfg_allowed if domain == "manufacturing" else project_allowed
    bad = n = 0
    for c in case_list:
        if not c["registered"]:
            continue
        want = {x.split("|", 1)[0] for x in ref.sets(c)["actionable"]}
        got = set()
        for aid, a in ref.actions.items():
            for b, res in ref.bindings(a, c["world"]["objects"]):
                if glue(c["principal"], aid, [r["key"] for r in res if r["actual"] == "Warehouse"]):
                    got.add(aid)
        n += 1
        bad += got != want
    return {"cases_compared": n, "cases_where_glue_differs_from_oracle": bad}


def report(domain: str, ir: dict, glue_fns: tuple, case_list: list) -> dict:
    doc = openapi(ir)
    return {"openapi_paths": len(doc["paths"]), "openapi_schemas": len(doc["components"]["schemas"]),
            "handwritten_authz_glue_loc": loc(*glue_fns), "glue_additions_per_new_action": 1,
            "glue_vs_oracle_on_actions_exposed": agreement(domain, ir, case_list),
            "note": "baseline exposes every action route; per-principal exposure needs the hand-written glue above (not generated, "
                    "no per-principal tool surface, no cardinality-aware accessors or Function/Action type split)"}
