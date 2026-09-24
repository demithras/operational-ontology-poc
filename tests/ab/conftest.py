from __future__ import annotations

import pytest

from tests.ab.harness import Harness


@pytest.fixture(scope="module")
def harness():
    h = Harness.create()
    yield h
    h.close()
