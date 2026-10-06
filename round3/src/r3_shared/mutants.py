"""Named mutants (deliberately weakened variant builds). Activated ONLY by constructing a variant with them:
`Variant.__init__(self, mutants: Iterable[str] = ())`, validated with `validate`. No global state."""
from __future__ import annotations

from typing import Iterable

KNOWN: dict[str, list[str]] = {
    "H23": ["identity_substitution", "mutable_gated_input", "backstop_bypass", "tool_overexposure"],
}  # later gates append their own key

ALL: frozenset[str] = frozenset(n for names in KNOWN.values() for n in names)


def validate(names: Iterable[str]) -> frozenset[str]:
    """Return the names as a frozenset; ValueError on any name not in any KNOWN list."""
    if isinstance(names, str):
        raise ValueError("mutants must be an iterable of names, not a single string")
    out = frozenset(names)
    unknown = sorted(out - ALL)
    if unknown:
        raise ValueError(f"unknown mutants {unknown}; known: {sorted(ALL)}")
    return out
