"""Compile authority-rule selectors of an IR package into data tables (generation time).

Grammar (docs/engine_semantics.md section 5): principal ``*`` | ``role:<r>`` | ``principal:<pid>`` | ``<T>#<rel>``;
resource ``*`` | ``<T>:*``; anything else is an opaque selector the domain must bind (kept as ("bound", text)).
"""
from __future__ import annotations


def type_lookup(ir: dict) -> dict:
    out: dict = {}
    for kind in ("object_types", "interfaces", "link_types"):
        for r in ir.get(kind, []):
            out.setdefault(r["id"].casefold(), set()).add(r["id"])
    return out


def _unique(look: dict, t: str):
    hits = look.get(t.casefold(), set())
    return next(iter(hits)) if len(hits) == 1 else None


def compile_principal(text: str, look: dict) -> list:
    if text == "*":
        return ["any"]
    for prefix, tag in (("role:", "role"), ("principal:", "principal")):
        if text.startswith(prefix) and len(text) > len(prefix):
            return [tag, text[len(prefix):]]
    if "#" in text:
        t, rel = text.split("#", 1)
        resolved = _unique(look, t) if t and rel else None
        if resolved:
            return ["relation", resolved, rel]
    return ["bound", text]


def compile_resource(text: str, look: dict) -> list:
    if text == "*":
        return ["any"]
    if text.endswith(":*") and len(text) > 2:
        resolved = _unique(look, text[:-2])
        if resolved:
            return ["type", resolved]
    return ["bound", text]


def compile_rule(rule: dict, look: dict) -> dict:
    return {"id": rule["id"], "principal": compile_principal(rule["principal_selector"], look), "capability": rule["capability"],
            "resource": compile_resource(rule["resource_selector"], look), "effect": rule["effect"],
            "delegation": bool(rule.get("delegation_allowed", False))}
