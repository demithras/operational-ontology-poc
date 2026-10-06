"""H23 mutant switches (names frozen in the protection spec). Off by default; a switch changes ONE decision point.

Activation: `PaladinVariant(mutants={...})`, `PaladinVariant().with_mutants(...)`, or env `PALADIN_MUTANTS=a,b`.
"""
from __future__ import annotations

import os

H23 = ("identity_substitution", "mutable_gated_input", "backstop_bypass", "tool_overexposure")
ENV = "PALADIN_MUTANTS"


def resolve(explicit=None) -> frozenset:
    names = set(explicit or ())
    env = os.environ.get(ENV, "")
    names |= {n.strip() for n in env.split(",") if n.strip()}
    unknown = names - set(H23)
    if unknown:
        raise ValueError(f"unknown Paladin mutant switch(es) {sorted(unknown)}; known: {list(H23)}")
    return frozenset(names)
