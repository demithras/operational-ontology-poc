"""The CI gate: accept a change (before files -> after files) iff no invariant is violated."""
from __future__ import annotations

from . import replication, rules
from .repo import Model

RULES = [rules.violations, replication.violations]


def check(before: dict, after: dict, evaluators: dict) -> list[str]:
    b, a = Model(before), Model(after)
    return [v for rule in RULES for v in rule(b, a, evaluators)]
