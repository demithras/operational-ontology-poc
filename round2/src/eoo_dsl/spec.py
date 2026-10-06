"""Typed structural check of a parsed DSL document, one-to-one with the IR fields.

The baseline does NOT delegate to the JSON Schema: it re-states the IR field table here so that a missing field,
an unknown key, a wrong type or a wrong enum is reported as a typed DslError naming the path. (A differential test
checks that it accepts exactly what the schema accepts.)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eoo_ir.kinds import (AUTHORITY_EFFECTS, DETERMINISM, EFFECT_OPERATIONS, IDEMPOTENCY, POLICY_DECISIONS, PRIMITIVES,
                          PURITY, SEVERITIES, TRUTH_STATUS)

from .errors import (DslConstraintError, DslEnumError, DslMissingField, DslTypeError, DslUnknownKey)


@dataclass(frozen=True)
class Str:
    min1: bool = False


@dataclass(frozen=True)
class Bool:
    pass


@dataclass(frozen=True)
class Enum:
    values: tuple


@dataclass(frozen=True)
class Const:
    value: str


@dataclass(frozen=True)
class List:
    item: Any
    min_items: int = 0


@dataclass(frozen=True)
class Obj:
    required: dict
    optional: dict


@dataclass(frozen=True)
class NullableStr:
    pass


@dataclass(frozen=True)
class Json:  # metadata: any JSON object
    pass


@dataclass(frozen=True)
class TypeExprSpec:
    pass


@dataclass(frozen=True)
class CardSpec:
    pass


S, S1, B = Str(), Str(True), Bool()
TYPE = TypeExprSpec()
PROPERTY = Obj({"name": S1, "type": TYPE, "required": B}, {"immutable": B, "description": S, "constraints": List(S)})
PARAM = Obj({"name": S, "type": TYPE}, {"required": B})
EFFECT = Obj({"target": S, "operation": Enum(EFFECT_OPERATIONS)}, {"fields": List(S)})
PACKAGE = Obj(
    {
        "package_id": S1, "version": S1,
        "object_types": List(Obj({"id": S1, "primary_key": S1, "properties": List(PROPERTY), "implements": List(S)}, {"description": S})),
        "link_types": List(Obj({"id": S1, "from": S1, "to": S1, "from_cardinality": CardSpec(), "to_cardinality": CardSpec()},
                               {"directed": B, "properties": List(PROPERTY)})),
        "interfaces": List(Obj({"id": S1, "required_properties": List(PROPERTY), "required_links": List(S), "capabilities": List(S)}, {})),
        "functions": List(Obj({"id": S1, "inputs": List(PARAM), "output": TYPE, "purity": Const(PURITY), "reads": List(S),
                               "implementation_ref": S1}, {"determinism": Enum(DETERMINISM)})),
        "actions": List(Obj({"id": S1, "inputs": List(PARAM), "authority_refs": List(S), "policy_refs": List(S),
                             "preconditions": List(S), "effects": List(EFFECT, 1), "idempotency": Enum(IDEMPOTENCY),
                             "outcome_predicate": S1, "version": S1}, {"compensation_action": NullableStr()})),
        "policies": List(Obj({"id": S, "decision": Enum(POLICY_DECISIONS), "expression_ref": S, "version": S}, {})),
        "authority_rules": List(Obj({"id": S, "principal_selector": S, "capability": S, "resource_selector": S,
                                     "effect": Enum(AUTHORITY_EFFECTS)}, {"delegation_allowed": B})),
        "observation_types": List(Obj({"id": S, "subject_type": S, "properties": List(PROPERTY), "source_binding": S,
                                       "truth_status": Const(TRUTH_STATUS)}, {})),
        "constraints": List(Obj({"id": S, "scope": S, "expression_ref": S, "severity": Enum(SEVERITIES)}, {})),
    },
    {"domain_id": S1, "imports": List(S), "metadata": Json()},
)


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def check(v: Any, spec: Any, path: str) -> None:
    here = path or "<root>"
    if isinstance(spec, Str):
        if not isinstance(v, str):
            raise DslTypeError(f"expected a string, got {type(v).__name__}", here)
        if spec.min1 and not v:
            raise DslConstraintError("must not be empty", here)
    elif isinstance(spec, Bool):
        if not isinstance(v, bool):
            raise DslTypeError(f"expected true/false, got {type(v).__name__}", here)
    elif isinstance(spec, NullableStr):
        if v is not None and not isinstance(v, str):
            raise DslTypeError(f"expected a string or null, got {type(v).__name__}", here)
    elif isinstance(spec, Enum):
        if not isinstance(v, str):
            raise DslTypeError(f"expected one of {list(spec.values)}, got {type(v).__name__}", here)
        if v not in spec.values:
            raise DslEnumError(f"{v!r} is not one of {list(spec.values)}", here)
    elif isinstance(spec, Const):
        if v != spec.value or not isinstance(v, str):
            raise DslEnumError(f"must be exactly {spec.value!r}", here)
    elif isinstance(spec, List):
        if not isinstance(v, list):
            raise DslTypeError(f"expected a list, got {type(v).__name__}", here)
        if len(v) < spec.min_items:
            raise DslConstraintError(f"needs at least {spec.min_items} item(s)", here)
        for i, x in enumerate(v):
            check(x, spec.item, f"{path}[{i}]")
    elif isinstance(spec, Obj):
        if not isinstance(v, dict):
            raise DslTypeError(f"expected a mapping, got {type(v).__name__}", here)
        for k in v:
            if k not in spec.required and k not in spec.optional:
                raise DslUnknownKey(f"unknown key {k!r}", here)
        for k, sub in spec.required.items():
            if k not in v:
                raise DslMissingField(f"missing required field {k!r}", here)
        for k, x in v.items():
            check(x, spec.required.get(k, spec.optional.get(k)), f"{path}.{k}" if path else k)
    elif isinstance(spec, Json):
        if not isinstance(v, dict) or not all(isinstance(k, str) for k in v):
            raise DslTypeError("metadata must be a mapping with string keys", here)
    elif isinstance(spec, TypeExprSpec):
        _check_type(v, here)
    elif isinstance(spec, CardSpec):
        _check_card(v, here)
    else:  # pragma: no cover
        raise AssertionError(spec)


def _check_type(v: Any, path: str) -> None:
    if isinstance(v, str):
        if v not in PRIMITIVES:
            raise DslEnumError(f"{v!r} is not a primitive type {list(PRIMITIVES)}", path)
        return
    if not isinstance(v, dict):
        raise DslTypeError(f"type must be a primitive name or one of {{ref|list|optional: ...}}, got {type(v).__name__}", path)
    for k in v:
        if k not in ("ref", "list", "optional"):
            raise DslUnknownKey(f"unknown type key {k!r}", path)
    if len(v) != 1:
        raise DslMissingField("a type constructor mapping must have exactly one of ref/list/optional", path)
    (k, x), = v.items()
    if k == "ref":
        if not isinstance(x, str):
            raise DslTypeError("ref must be a string", path + ".ref")
    else:
        _check_type(x, f"{path}.{k}")


def _check_card(v: Any, path: str) -> None:
    if not isinstance(v, dict):
        raise DslTypeError("cardinality must be a mapping {min, max}", path)
    for k in v:
        if k not in ("min", "max"):
            raise DslUnknownKey(f"unknown key {k!r}", path)
    for k in ("min", "max"):
        if k not in v:
            raise DslMissingField(f"cardinality is missing {k!r}", path)
    if not _is_int(v["min"]):
        raise DslTypeError("cardinality min must be an integer", path + ".min")
    if v["min"] < 0:
        raise DslConstraintError("cardinality min must be >= 0", path + ".min")
    mx = v["max"]
    if mx == "*" and isinstance(mx, str):
        return
    if not _is_int(mx):
        raise DslTypeError("cardinality max must be an integer >= 1 or '*'", path + ".max")
    if mx < 1:
        raise DslConstraintError("cardinality max must be >= 1 or '*'", path + ".max")
