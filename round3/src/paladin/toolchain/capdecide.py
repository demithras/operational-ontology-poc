"""The Toolchain's own capability decision (generic): evaluates the compiled authority tables of a generated surface.

Semantics follow docs/engine_semantics.md section 5 (written from the document, not imported from the Engine):
deny on the principal or any delegation-chain principal overrides; an allow applies to a delegator-free principal,
to a delegate only when the rule permits delegation and the delegator is itself allowed; a selector failure denies.
Resources are tuples (declared, key, actual); key is None for effect targets.
"""
from __future__ import annotations

from types import SimpleNamespace


def cap_match(pattern: str, cap: str) -> bool:
    return pattern == cap or pattern == "*" or (pattern.endswith(":*") and cap.startswith(pattern[:-1]))


def conforms(tables: dict, actual: str, declared: str) -> bool:
    return actual == declared or actual in tables["implementers"].get(declared, ())


class _Fail(Exception):
    pass


def _opaque(opaque: dict, text: str, who, cap, resources, world):
    fn = (opaque or {}).get(text)
    if fn is None:
        raise _Fail(f"no binding for selector {text!r}")
    out = fn(SimpleNamespace(principal=who, capability=cap, world=world, view=getattr(world, "view", None),
                             resources=tuple(SimpleNamespace(declared=d, key=k, actual=a) for d, k, a in resources)))
    if not isinstance(out, bool):
        raise _Fail("selector returned a non-bool")
    return out


def _principal_ok(sel, who, cap, resources, tables, opaque, world) -> bool:
    tag = sel[0]
    if tag == "any":
        return True
    if tag == "role":
        return sel[1] in who.roles
    if tag == "principal":
        return sel[1] == who.pid
    if tag == "relation":
        bound = [r for r in resources if r[1] is not None and conforms(tables, r[2], sel[1])]
        return bool(bound) and all((r[2], r[1], sel[2]) in who.relations for r in bound)
    return _opaque(opaque, sel[1], who, cap, resources, world)


def _resource_ok(sel, who, cap, resources, tables, opaque, world) -> bool:
    tag = sel[0]
    if tag == "any":
        return True
    if tag == "type":
        return any(r[0] == sel[1] or conforms(tables, r[2], sel[1]) for r in resources)
    return _opaque(opaque, sel[1], who, cap, resources, world)


def _chain(who):
    while who is not None:
        yield who
        who = who.delegated_by


def decide(tables: dict, refs: list, who, cap: str, resources: tuple, opaque=None, world=None) -> bool:
    """True iff ``who`` may exercise ``cap`` over ``resources`` under the rules named by ``refs`` (rule ids / import marks)."""
    allowed, errored = _decide(tables, refs, who, cap, resources, opaque, world, 0)
    return allowed and not errored


def _decide(tables, refs, who, cap, resources, opaque, world, depth) -> tuple:
    if depth > 16:
        return False, True
    allow = deny = error = False
    for ref in refs:
        rule = tables["rules"].get(ref)
        if rule is None:  # import-qualified reference: needs a binding the Toolchain does not have
            error = True
            continue
        if not cap_match(rule["capability"], cap):
            continue
        try:
            if rule["effect"] == "deny":
                if any(_principal_ok(rule["principal"], w, cap, resources, tables, opaque, world)
                       and _resource_ok(rule["resource"], w, cap, resources, tables, opaque, world) for w in _chain(who)):
                    deny = True
                continue
            if not (_principal_ok(rule["principal"], who, cap, resources, tables, opaque, world)
                    and _resource_ok(rule["resource"], who, cap, resources, tables, opaque, world)):
                continue
            if who.delegated_by is None:
                allow = True
            elif rule["delegation"]:
                ok, err = _decide(tables, refs, who.delegated_by, cap, resources, opaque, world, depth + 1)
                allow, error = (allow or (ok and not err)), (error or err)
        except _Fail:
            error = True
            deny = True
        except Exception:  # noqa: BLE001 - a broken selector fails closed
            error = True
            deny = True
    return (allow and not deny and not error), error
