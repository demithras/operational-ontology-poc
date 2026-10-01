"""Every generated package must pass the oracle's own validator."""
import json

from hypothesis import given

from eoo_ir import validate
from eoo_ir.strategies import valid_packages


@given(valid_packages())
def test_generated_packages_validate(pkg):
    assert validate(pkg) == [], json.dumps(pkg)[:2000]
