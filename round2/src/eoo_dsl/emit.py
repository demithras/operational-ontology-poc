"""Render an IR package as DSL text: YAML, keys named exactly like the IR fields, schema key order.

Absent optional fields stay absent (no defaults are written); array order is preserved. Strings are written
plain only when they cannot be mistaken for another scalar, otherwise double-quoted with ASCII-only escapes.
"""
from __future__ import annotations

import math
import re
from typing import Any

_PLAIN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:[.\-][A-Za-z0-9_]+)*$")
_RESERVED = {"y", "n", "yes", "no", "true", "false", "on", "off", "null", "~"}

_ORDER = {
    "package": ["package_id", "domain_id", "version", "imports", "object_types", "link_types", "interfaces", "functions",
                "actions", "policies", "authority_rules", "observation_types", "constraints", "metadata"],
    "object_types": ["id", "primary_key", "properties", "implements", "description"],
    "link_types": ["id", "from", "to", "from_cardinality", "to_cardinality", "directed", "properties"],
    "interfaces": ["id", "required_properties", "required_links", "capabilities"],
    "functions": ["id", "inputs", "output", "purity", "reads", "implementation_ref", "determinism"],
    "actions": ["id", "inputs", "authority_refs", "policy_refs", "preconditions", "effects", "idempotency",
                "outcome_predicate", "compensation_action", "version"],
    "policies": ["id", "decision", "expression_ref", "version"],
    "authority_rules": ["id", "principal_selector", "capability", "resource_selector", "effect", "delegation_allowed"],
    "observation_types": ["id", "subject_type", "properties", "source_binding", "truth_status"],
    "constraints": ["id", "scope", "expression_ref", "severity"],
    "property": ["name", "type", "required", "immutable", "description", "constraints"],
    "parameter": ["name", "type", "required"],
    "effect": ["target", "operation", "fields"],
    "cardinality": ["min", "max"],
}
_CHILD_CTX = {
    ("package", k): k for k in ("object_types", "link_types", "interfaces", "functions", "actions", "policies",
                                "authority_rules", "observation_types", "constraints")
}
_CHILD_CTX.update({
    ("object_types", "properties"): "property", ("link_types", "properties"): "property",
    ("interfaces", "required_properties"): "property", ("observation_types", "properties"): "property",
    ("functions", "inputs"): "parameter", ("actions", "inputs"): "parameter", ("actions", "effects"): "effect",
    ("link_types", "from_cardinality"): "cardinality", ("link_types", "to_cardinality"): "cardinality",
})
_FLOW_KEYS = {"type", "output"}  # type expressions are written inline: {list: {optional: string}}


def quote(s: str) -> str:
    out = ['"']
    for ch in s:
        o = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        elif 0x20 <= o <= 0x7E:
            out.append(ch)
        elif o < 0x10000:
            out.append(f"\\u{o:04x}")
        else:
            out.append(f"\\U{o:08x}")
    out.append('"')
    return "".join(out)


def string(s: str) -> str:
    return s if _PLAIN.fullmatch(s) is not None and s.lower() not in _RESERVED else quote(s)


def scalar(v: Any) -> str:
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if not math.isfinite(v):
            raise ValueError("non-finite float cannot be written in the DSL")
        return repr(v)
    if isinstance(v, str):
        return string(v)
    raise TypeError(f"cannot render {type(v).__name__}")


def flow(v: Any) -> str:
    if isinstance(v, dict):
        return "{" + ", ".join(f"{string(str(k))}: {flow(x)}" for k, x in v.items()) + "}"
    if isinstance(v, list):
        return "[" + ", ".join(flow(x) for x in v) + "]"
    return scalar(v)


def _keys(d: dict, ctx: str) -> list:
    order = _ORDER.get(ctx, [])
    return [k for k in order if k in d] + sorted((k for k in d if k not in order), key=str)


def _map(d: dict, ind: int, ctx: str, first_prefix: str | None = None) -> list[str]:
    lines: list[str] = []
    for n, k in enumerate(_keys(d, ctx)):
        v = d[k]
        pad = " " * ind
        head = (first_prefix if (n == 0 and first_prefix is not None) else pad) + string(str(k)) + ":"
        if ctx == "package" and k == "metadata" or k in _FLOW_KEYS and ctx != "package":
            lines.append(f"{head} {flow(v)}")
        elif isinstance(v, dict) and v:
            lines.append(head)
            lines += _map(v, ind + 2, _CHILD_CTX.get((ctx, k), "?"))
        elif isinstance(v, list) and v and any(isinstance(x, dict) and x for x in v) and \
                all(isinstance(x, dict) for x in v):
            lines.append(head)
            for item in v:
                if item:
                    lines += _map(item, ind + 4, _CHILD_CTX.get((ctx, k), "?"), first_prefix=" " * (ind + 2) + "- ")
                else:
                    lines.append(" " * (ind + 2) + "- {}")
        else:
            lines.append(f"{head} {flow(v)}")
    return lines


def render(ir: dict) -> str:
    return "\n".join(_map(ir, 0, "package")) + "\n"
