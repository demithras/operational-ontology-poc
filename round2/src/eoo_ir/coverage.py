"""Coverage of what a sample of generated packages reached (used by the oracle coverage test)."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from .gen_atoms import KEYWORDS
from .kinds import (AUTHORITY_EFFECTS, DETERMINISM, EFFECT_OPERATIONS, IDEMPOTENCY, POLICY_DECISIONS, PRIMITIVES,
                    RESOURCE_ARRAYS, SEVERITIES)

BOOL = (True, False)
LIST_FIELDS = {  # label -> (resource kind or None for package level, key)
    "imports": (None, "imports"), "implements": ("object_types", "implements"),
    "object.properties": ("object_types", "properties"), "required_links": ("interfaces", "required_links"),
    "capabilities": ("interfaces", "capabilities"), "interface.required_properties": ("interfaces", "required_properties"),
    "function.inputs": ("functions", "inputs"), "function.reads": ("functions", "reads"),
    "action.inputs": ("actions", "inputs"), "action.authority_refs": ("actions", "authority_refs"),
    "action.policy_refs": ("actions", "policy_refs"), "action.preconditions": ("actions", "preconditions"),
    "link.properties": ("link_types", "properties"), "observation.properties": ("observation_types", "properties"),
}
OPTIONAL = {  # label -> (kind or None, key)
    "package.domain_id": (None, "domain_id"), "package.imports": (None, "imports"), "package.metadata": (None, "metadata"),
    "object.description": ("object_types", "description"), "link.directed": ("link_types", "directed"),
    "link.properties": ("link_types", "properties"), "function.determinism": ("functions", "determinism"),
    "action.compensation_action": ("actions", "compensation_action"),
    "authority.delegation_allowed": ("authority_rules", "delegation_allowed"),
}


def expected() -> dict[str, set]:
    e: dict[str, set] = {
        "resource_kind": set(RESOURCE_ARRAYS), "primitive": set(PRIMITIVES), "type_constructor": {"ref", "list", "optional"},
        "type_nesting": {"nested>=2"}, "effect_operation": set(EFFECT_OPERATIONS), "policy_decision": set(POLICY_DECISIONS),
        "idempotency": set(IDEMPOTENCY), "authority_effect": set(AUTHORITY_EFFECTS), "severity": set(SEVERITIES),
        "determinism": set(DETERMINISM) | {"<absent>"}, "cardinality_max": {"int", "*"}, "cardinality_min": {0, ">0"},
        "compensation_action": {"<absent>", "null", "str"}, "atom_class": {"unicode", "space", "quote", "newline", "keyword", "empty"},
        "import_qualified_ref": {True}, "function_action_same_id": {True}, "effect_count": {1, ">1"},
    }
    for label in ("property.required", "property.immutable", "link.directed", "authority.delegation_allowed",
                  "parameter.required"):
        e[label] = set(BOOL)
    for label in LIST_FIELDS:
        e["list:" + label] = {"empty", "non-empty"}
    # primary_key must name a property, so an object type with zero properties can never be valid.
    e["list:object.properties"] = {"non-empty"}
    for label in OPTIONAL:
        e["optional:" + label] = {"present", "absent"}
    return e


def _types(te: Any, depth: int = 0) -> Iterable[tuple[str, int]]:
    if isinstance(te, str):
        yield te, depth
    elif isinstance(te, dict):
        for k in ("ref", "list", "optional"):
            if k in te:
                yield k, depth
                if k != "ref":
                    yield from _types(te[k], depth + 1)


def observe(pkg: dict, t: dict[str, set]) -> None:
    add = lambda k, v: t[k].add(v)  # noqa: E731
    for kind in RESOURCE_ARRAYS:
        if pkg[kind]:
            add("resource_kind", kind)
    for label, (kind, key) in LIST_FIELDS.items():
        for holder in ([pkg] if kind is None else pkg[kind]):
            if key in holder:
                add("list:" + label, "non-empty" if holder[key] else "empty")
    for label, (kind, key) in OPTIONAL.items():
        for holder in ([pkg] if kind is None else (pkg[kind] or [])):
            add("optional:" + label, "present" if key in holder else "absent")
    props, params, tes = [], [], []
    for kind, key in (("object_types", "properties"), ("link_types", "properties"), ("interfaces", "required_properties"),
                      ("observation_types", "properties")):
        for r in pkg[kind]:
            props += r.get(key, [])
    for r in pkg["functions"]:
        params += r["inputs"]
        tes.append(r["output"])
        add("determinism", r.get("determinism", "<absent>"))
    for r in pkg["actions"]:
        params += r["inputs"]
        add("idempotency", r["idempotency"])
        add("effect_count", 1 if len(r["effects"]) == 1 else ">1")
        add("compensation_action", "<absent>" if "compensation_action" not in r else "null" if r["compensation_action"] is None else "str")
        for e in r["effects"]:
            add("effect_operation", e["operation"])
    for p in props:
        tes.append(p["type"])
        add("property.required", p["required"])
        if "immutable" in p:
            add("property.immutable", p["immutable"])
    for q in params:
        tes.append(q["type"])
        if "required" in q:
            add("parameter.required", q["required"])
    for te in tes:
        for name, depth in _types(te):
            add("primitive" if name in PRIMITIVES else "type_constructor", name)
            if depth >= 2:
                add("type_nesting", "nested>=2")
    for r in pkg["link_types"]:
        if "directed" in r:
            add("link.directed", r["directed"])
        for w in ("from_cardinality", "to_cardinality"):
            c = r[w]
            add("cardinality_max", "*" if c["max"] == "*" else "int")
            add("cardinality_min", 0 if c["min"] == 0 else ">0")
    for r in pkg["policies"]:
        add("policy_decision", r["decision"])
    for r in pkg["authority_rules"]:
        add("authority_effect", r["effect"])
        if "delegation_allowed" in r:
            add("authority.delegation_allowed", r["delegation_allowed"])
    for r in pkg["constraints"]:
        add("severity", r["severity"])
    if {r["id"] for r in pkg["functions"]} & {r["id"] for r in pkg["actions"]}:
        add("function_action_same_id", True)
    imps = pkg.get("imports", [])
    strings = [pkg["package_id"], pkg["version"]] + [r["id"] for k in RESOURCE_ARRAYS for r in pkg[k]]
    strings += [r["expression_ref"] for k in ("policies", "constraints") for r in pkg[k]] + [r["capability"] for r in pkg["authority_rules"]]
    if "" in strings:
        add("atom_class", "empty")
    for s in strings:
        if any(ord(c) > 127 for c in s):
            add("atom_class", "unicode")
        if " " in s:
            add("atom_class", "space")
        if '"' in s or "'" in s:
            add("atom_class", "quote")
        if "\n" in s:
            add("atom_class", "newline")
        if s in KEYWORDS:
            add("atom_class", "keyword")
    for r in pkg["link_types"]:
        if any(r[e].startswith(i + "#") for e in ("from", "to") for i in imps):
            add("import_qualified_ref", True)


def new_table() -> dict[str, set]:
    return defaultdict(set)


def missing(table: dict[str, set]) -> dict[str, set]:
    return {k: v - table.get(k, set()) for k, v in expected().items() if v - table.get(k, set())}


def render_table(table: dict[str, set]) -> str:
    rows = []
    for k, v in sorted(expected().items()):
        got = table.get(k, set())
        rows.append(f"{k:42s} {len(v & got)}/{len(v)}  missing={sorted(map(str, v - got))}")
    return "\n".join(rows)
