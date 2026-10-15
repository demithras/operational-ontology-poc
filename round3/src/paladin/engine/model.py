"""Compiled, immutable view of one IR package (built by registry.py through DISPATCH_TABLE)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class Param:
    pname: str
    type: Any
    required: bool


@dataclass(frozen=True)
class ObjSpec:
    rid: str
    pk: str
    props: dict  # property name -> IR property dict
    implements: tuple


@dataclass(frozen=True)
class LinkSpec:
    rid: str
    src: str
    dst: str
    src_max: Any  # max links per from-object (from_cardinality.max)
    dst_max: Any  # max links per to-object (to_cardinality.max)
    src_min: int
    dst_min: int
    props: dict


@dataclass(frozen=True)
class IfaceSpec:
    rid: str
    required_properties: tuple
    required_links: tuple
    caps: tuple


@dataclass(frozen=True)
class FnSpec:
    rid: str
    inputs: tuple
    output: Any
    impl_ref: str


@dataclass(frozen=True)
class EffectSpec:
    index: int
    operation: str
    target: str
    fields: Optional[tuple]
    target_kind: str  # object_types | link_types | import | system
    plan: Optional[dict]  # derivation plan; None -> payload binding required


@dataclass(frozen=True)
class ActionSpec:
    rid: str
    version: str
    inputs: tuple
    auth_refs: tuple  # (ref text, local rule id or None for import-qualified)
    policy_refs: tuple  # (ref text, local policy id or None)
    preconditions: tuple
    effects: tuple
    idempotency: str
    outcome_predicate: str
    compensation: Optional[str]


@dataclass(frozen=True)
class PolicySpec:
    rid: str
    decision: str
    expr: str
    version: str


@dataclass(frozen=True)
class RuleSpec:
    rid: str
    principal_sel: tuple  # parsed selector, see authority.py
    capability: str
    resource_sel: tuple
    effect: str
    delegation: bool
    raw_principal: str
    raw_resource: str


@dataclass(frozen=True)
class ObsSpec:
    rid: str
    subject_type: str
    props: dict


@dataclass(frozen=True)
class ConstraintSpec:
    rid: str
    scope: str
    expr: str
    severity: str


@dataclass
class Model:
    package_id: str
    version: str
    imports: tuple
    kinds: dict = field(default_factory=dict)  # kind name -> {resource id -> spec}
    implementers: dict = field(default_factory=dict)  # interface id -> set of object type ids
    required: list = field(default_factory=list)  # Unbound items the package needs bound

    def get(self, kind: str, rid: str):
        return self.kinds.get(kind, {}).get(rid)

    def all(self, kind: str) -> dict:
        return self.kinds.get(kind, {})

    def is_import(self, ref: str) -> bool:
        return any(ref.startswith(i + "#") and len(ref) > len(i) + 1 for i in self.imports)

    def conforms(self, actual_type: str, declared: str) -> bool:
        """An object of ``actual_type`` may stand where ``declared`` (type or interface) is expected."""
        return actual_type == declared or actual_type in self.implementers.get(declared, ())
