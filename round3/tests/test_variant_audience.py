"""The harness reads each variant's token audience from the class attribute `audience` (no auto-detection)."""
import pytest

from r3_shared.registry import load_variant


@pytest.mark.parametrize("name", ["paladin", "conventional"])
def test_variant_declares_its_audience(name):
    assert type(load_variant(name)).audience == name
