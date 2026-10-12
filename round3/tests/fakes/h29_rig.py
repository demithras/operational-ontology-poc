"""Service-set rig for the H29 tests: re-export of r3_harness.h29.svcset.SvcSet plus fake-variant names."""
from __future__ import annotations

from r3_harness.h29.svcset import SvcSet  # noqa: F401

FAKE = "tests.fakes.fake_h29:FakeHonestG5"


def fake(name: str) -> str:
    return f"tests.fakes.fake_h29:{name}"
