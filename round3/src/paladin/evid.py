"""The four artifact kinds bound by a decision (PROT-H27 s1) and their content addresses (sha256 of canonical bytes, s3)."""
from __future__ import annotations

import hashlib
from typing import Any, Callable

from r3_shared.evidence import canonical_bytes

NULL_BYTES = canonical_bytes(None)


def digest(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def has_float(x: Any) -> bool:
    if isinstance(x, float):
        return True
    if isinstance(x, dict):
        return any(has_float(v) for v in x.values())
    if isinstance(x, (list, tuple)):
        return any(has_float(v) for v in x)
    return False


def input_refs(ops_spec: dict, op: str, args: dict) -> list[tuple[str, str]]:
    """(resource type, key) of every resource-typed input present in the request."""
    spec = next(o for o in ops_spec["operations"] if o["name"] == op)
    return [(i["resource_type"], args[i["name"]]) for i in spec["inputs"]
            if i["type"] == "resource" and isinstance(args.get(i["name"]), str)]


def newest_terms(node: Any) -> list[tuple[str, str]]:
    """Every {"newest": {"type": T, "field": f}} term in an expression tree: [(T, field)]."""
    out: list = []
    if isinstance(node, dict):
        if "newest" in node and isinstance(node["newest"], dict):
            out.append((node["newest"]["type"], node["newest"]["field"]))
        for v in node.values():
            out += newest_terms(v)
    elif isinstance(node, list):
        for v in node:
            out += newest_terms(v)
    return out


def evidence_objects(ops_spec: dict, op: str, args: dict, get: Callable, lst: Callable) -> list[dict]:
    """The FROZEN EVIDENCE SET read through `get(type,key)` / `lst(type)`: resource inputs + the object each `newest` term selects."""
    spec = next(o for o in ops_spec["operations"] if o["name"] == op)
    out, seen = [], set()

    def bind(t: str, k: str) -> None:
        if (t, k) in seen:
            return
        seen.add((t, k))
        row = get(t, k)
        out.append({"ref": f"{t}:{k}", "absent": True} if row is None
                   else {"ref": f"{t}:{k}", "version": row["version"], "props": row["props"]})

    for t, k in input_refs(ops_spec, op, args):
        bind(t, k)
    for t, f in sorted(set(newest_terms(spec.get("business_rules", [])) + newest_terms(spec.get("preconditions", [])))):
        rows = [r for r in lst(t) if isinstance(r["props"].get(f), int) and not isinstance(r["props"].get(f), bool)]
        if rows:
            bind(t, min(rows, key=lambda r: (-r["props"][f], r["key"]))["key"])
    return out


def policy_of(ops_spec: dict, op: str | None) -> Any:
    if op is None:
        return None
    o = next(x for x in ops_spec["operations"] if x["name"] == op)
    return {"config": ops_spec["config"], "business_rules": o.get("business_rules"), "approval": o.get("approval")}


def contract_of(ops_spec: dict, op: str | None) -> Any:
    if op is None:
        return None
    o = next(x for x in ops_spec["operations"] if x["name"] == op)
    return {**{k: v for k, v in o.items() if k not in ("business_rules", "approval")}, "helpers": ops_spec["helpers"],
            "spec": ops_spec["spec"]}


def artifact_set(ops_spec: dict, op: str | None, doc: dict, evidence: list[dict]) -> dict:
    """{"evidence": [bytes...], "authority": bytes, "policy": bytes, "contract": bytes} (canonical bytes)."""
    return {"evidence": [canonical_bytes(e) for e in evidence], "authority": canonical_bytes(doc),
            "policy": canonical_bytes(policy_of(ops_spec, op)), "contract": canonical_bytes(contract_of(ops_spec, op))}
