"""Mutant switches (planted bugs) shared by variants and the harness mutation proof.

Names are frozen in KNOWN (protection spec PROT-H23). A variant consults `is_on(name)` at the place where the real
bug would live. The harness turns a switch on for one run via `enabled(...)`. All switches are off by default.
"""
from __future__ import annotations

from contextlib import contextmanager

KNOWN: dict[str, tuple[str, ...]] = {
    "H23": ("identity_substitution", "mutable_gated_input", "backstop_bypass", "tool_overexposure"),
}

_ON: set[str] = set()


def _check(name: str) -> None:
    if not any(name in names for names in KNOWN.values()):
        raise KeyError(f"unknown mutant {name!r}")


def is_on(name: str) -> bool:
    return name in _ON


def enable(name: str) -> None:
    _check(name)
    _ON.add(name)


def disable(name: str) -> None:
    _ON.discard(name)


def reset() -> None:
    _ON.clear()


def active() -> set[str]:
    return set(_ON)


@contextmanager
def enabled(*names: str):
    for n in names:
        _check(n)
    before = set(_ON)
    _ON.update(names)
    try:
        yield
    finally:
        _ON.clear()
        _ON.update(before)
