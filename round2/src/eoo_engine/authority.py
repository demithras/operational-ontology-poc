"""Generic interpreter for IR authority_rules. Grammar (domain-neutral, see docs/engine_semantics.md):

principal_selector:  ``*`` | ``role:<r>`` | ``principal:<pid>`` | ``<T>#<rel>``
    ``<T>#<rel>``: every action input bound to an object conforming to type/interface T (matched
    case-insensitively, must resolve uniquely) is an object on which the principal holds ``rel``;
    at least one such input must exist.
resource_selector:   ``*`` | ``<T>:*`` (some resource of the request conforms to T)
capability:          exact string | ``*`` | ``<prefix>:*``
Any other selector text is opaque: it must be bound by the domain pack (kind principal_selector /
resource_selector) or the package does not load. Deny overrides allow; no matching allow = deny.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

DECIDE_ALLOW, DECIDE_DENY = "allow", "deny"


@dataclass(frozen=True)
class Principal:
    pid: str
    roles: frozenset = frozenset()
    relations: frozenset = frozenset()  # {(object type, key, relation)}
    delegated_by: Optional["Principal"] = None

    def __post_init__(self):
        object.__setattr__(self, "roles", frozenset(self.roles))
        object.__setattr__(self, "relations", frozenset(tuple(r) for r in self.relations))

    def chain(self) -> list["Principal"]:
        out, p = [], self
        while p is not None:
            out.append(p)
            p = p.delegated_by
        return out

    def to_plain(self) -> dict:
        return {"pid": self.pid, "roles": sorted(self.roles), "relations": sorted(list(r) for r in self.relations),
                "delegated_by": None if self.delegated_by is None else self.delegated_by.to_plain()}

    @classmethod
    def from_plain(cls, d: dict) -> "Principal":
        db = d.get("delegated_by")
        return cls(d["pid"], frozenset(d.get("roles", [])), frozenset(tuple(r) for r in d.get("relations", [])),
                   None if db is None else cls.from_plain(db))


@dataclass(frozen=True)
class Resource:
    declared: str  # declared type / interface / link type / effect target
    key: Any  # object key, None for effect targets
    actual: str  # concrete object type (== declared for targets)


def type_lookup(model) -> dict:
    out: dict = {}
    for kind in ("object_types", "interfaces", "link_types"):
        for rid in model.all(kind):
            out.setdefault(rid.casefold(), set()).add(rid)
    return out


def _unique(lookup: dict, t: str) -> Optional[str]:
    hits = lookup.get(t.casefold(), set())
    return next(iter(hits)) if len(hits) == 1 else None


def parse_principal(text: str, lookup: dict) -> tuple:
    if text == "*":
        return ("any",)
    for prefix, tag in (("role:", "role"), ("principal:", "principal")):
        if text.startswith(prefix) and len(text) > len(prefix):
            return (tag, text[len(prefix):])
    if "#" in text:
        t, rel = text.split("#", 1)
        resolved = _unique(lookup, t) if t and rel else None
        if resolved:
            return ("relation", resolved, rel)
    return ("bound", text)


def parse_resource(text: str, lookup: dict) -> tuple:
    if text == "*":
        return ("any",)
    if text.endswith(":*") and len(text) > 2:
        resolved = _unique(lookup, text[:-2])
        if resolved:
            return ("type", resolved)
    return ("bound", text)


def capability_matches(pattern: str, cap: str) -> bool:
    return pattern == cap or pattern == "*" or (pattern.endswith(":*") and cap.startswith(pattern[:-1]))


@dataclass(frozen=True)
class SelectorContext:
    """What a bound selector predicate may see (read-only)."""
    principal: Principal
    capability: str
    resources: tuple
    view: Any


@dataclass
class Decision:
    allowed: bool = False
    allow: list = field(default_factory=list)
    deny: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    def to_plain(self) -> dict:
        return {"allowed": self.allowed, "allow": self.allow, "deny": self.deny, "errors": self.errors}


def _bool_call(fn, ctx) -> bool:
    out = fn(ctx)
    if not isinstance(out, bool):
        raise TypeError(f"selector predicate returned {type(out).__name__}, expected bool")
    return out


def principal_matches(sel: tuple, p: Principal, resources: tuple, model, bindings, sctx) -> bool:
    tag = sel[0]
    if tag == "any":
        return True
    if tag == "role":
        return sel[1] in p.roles
    if tag == "principal":
        return sel[1] == p.pid
    if tag == "relation":
        _, t, rel = sel
        bound = [r for r in resources if r.key is not None and model.conforms(r.actual, t)]
        return bool(bound) and all((r.actual, r.key, rel) in p.relations for r in bound)
    return _bool_call(bindings.get("principal_selector", sel[1]), sctx)


def resource_matches(sel: tuple, resources: tuple, model, bindings, sctx) -> bool:
    tag = sel[0]
    if tag == "any":
        return True
    if tag == "type":
        return any(r.declared == sel[1] or model.conforms(r.actual, sel[1]) for r in resources)
    return _bool_call(bindings.get("resource_selector", sel[1]), sctx)


def evaluate(refs: tuple, principal: Principal, capability: str, resources: tuple, model, bindings, view,
             _depth: int = 0) -> Decision:
    """Decide ``capability`` for ``principal`` over the rules named by ``refs`` ((text, local id|None))."""
    d = Decision()
    if _depth > 16:
        d.errors.append("delegation chain too deep")
        return d
    for text, rid in refs:
        try:
            if rid is None:  # import-qualified rule: evaluated by its binding
                sctx = SelectorContext(principal, capability, resources, view)
                verdict = bindings.get("authority_import", text)(sctx)
                if verdict not in (DECIDE_ALLOW, DECIDE_DENY, None):
                    raise TypeError(f"authority_import binding returned {verdict!r}")
                if verdict == DECIDE_DENY:
                    d.deny.append(text)
                elif verdict == DECIDE_ALLOW:
                    d.allow.append(text)
                continue
            rule = model.get("authority_rules", rid)
            if not capability_matches(rule.capability, capability):
                continue
            if rule.effect == DECIDE_DENY:
                for who in principal.chain():  # a deny on any principal in the delegation chain applies
                    sctx = SelectorContext(who, capability, resources, view)
                    if principal_matches(rule.principal_sel, who, resources, model, bindings, sctx) and \
                            resource_matches(rule.resource_sel, resources, model, bindings, sctx):
                        d.deny.append(rid)
                        break
                continue
            sctx = SelectorContext(principal, capability, resources, view)
            if not (principal_matches(rule.principal_sel, principal, resources, model, bindings, sctx)
                    and resource_matches(rule.resource_sel, resources, model, bindings, sctx)):
                continue
            if principal.delegated_by is None:
                d.allow.append(rid)
            elif rule.delegation:
                inner = evaluate(refs, principal.delegated_by, capability, resources, model, bindings, view, _depth + 1)
                if inner.allowed:
                    d.allow.append(rid)
                d.errors += inner.errors
        except Exception as exc:  # fail closed: a broken selector counts as a deny
            d.errors.append(f"{text}: {type(exc).__name__}: {exc}")
            d.deny.append(text)
    d.allowed = bool(d.allow) and not d.deny and not d.errors
    return d
