"""LogicBindings: domain logic registered by IR ref. The Engine decides WHEN logic runs and how
results combine; logic receives read-only context and returns values only.

Binding namespaces (kind -> key):
  function           Function.implementation_ref     impl(view, args) -> output value
  policy             Policy.expression_ref           pred(ctx) -> bool  (True = the policy applies)
  precondition       Action.preconditions[i] text    pred(ctx) -> bool  (True = satisfied)
  constraint         Constraint.expression_ref       pred(ctx) -> bool  (True = holds on would-be state)
  outcome_predicate  Action.outcome_predicate text   pred(ctx) -> True | False | None (None = unknown)
  principal_selector / resource_selector  opaque selector text   pred(SelectorContext) -> bool
  authority_import   import-qualified authority ref  f(SelectorContext) -> "allow" | "deny" | None
  policy_import      import-qualified policy ref     f(ctx) -> "allow"|"deny"|"require_approval"|"classify"|None
  payload            "<action id>#<effect index>"    f(ctx) -> dict (effect payload, see effects.py)
An unbound key needed by the package is an ``Unbound`` load error, never a default.
"""
from __future__ import annotations

from typing import Callable, Iterable

from .errors import Unbound

KINDS = ("function", "policy", "precondition", "constraint", "outcome_predicate", "principal_selector",
         "resource_selector", "authority_import", "policy_import", "payload")


class LogicBindings:
    def __init__(self, mapping: dict | None = None):
        self._fns: dict[tuple[str, str], Callable] = {}
        for kind, table in (mapping or {}).items():
            for key, fn in table.items():
                self.bind(kind, key, fn)

    def bind(self, kind: str, key: str, fn: Callable) -> "LogicBindings":
        if kind not in KINDS:
            raise ValueError(f"unknown binding kind {kind!r}; expected one of {KINDS}")
        if not callable(fn):
            raise TypeError(f"binding {kind}:{key!r} is not callable")
        self._fns[(kind, key)] = fn
        return self

    def has(self, kind: str, key: str) -> bool:
        return (kind, key) in self._fns

    def get(self, kind: str, key: str) -> Callable:
        try:
            return self._fns[(kind, key)]
        except KeyError:
            raise LookupError(f"unbound {kind} {key!r}") from None

    def keys(self) -> list[tuple[str, str]]:
        return sorted(self._fns)

    def missing(self, required: Iterable[Unbound]) -> list[Unbound]:
        return [u for u in required if not self.has(u.kind, u.key)]
