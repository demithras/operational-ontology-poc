"""Test-only mutant switches for H23 (names frozen in the protection spec). Each switch re-introduces one real bug at the
place where it would live (see spec/protections/H23-conventional.md). Off by default; never enable in production."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterable, Iterator

KNOWN = ("identity_substitution", "mutable_gated_input", "backstop_bypass", "tool_overexposure")
_GLOBAL: set[str] = set()


def validate(names: Iterable[str]) -> frozenset[str]:
    names = frozenset(names)
    bad = names - set(KNOWN)
    if bad:
        raise ValueError(f"unknown mutant switch(es): {sorted(bad)}; known: {list(KNOWN)}")
    return names


def is_on(name: str, local: frozenset[str] = frozenset()) -> bool:
    return name in local or name in _GLOBAL


@contextmanager
def enabled(*names: str) -> Iterator[None]:
    """Process-wide switch for the duration of the block (affects every conventional deployment)."""
    added = set(validate(names)) - _GLOBAL
    _GLOBAL.update(added)
    try:
        yield
    finally:
        _GLOBAL.difference_update(added)
