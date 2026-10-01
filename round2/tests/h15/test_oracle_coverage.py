"""Coverage: a fixed-seed sample of 2,000 generated packages must reach every enum member, boolean value,
resource kind, cardinality form, list emptiness, optional-field presence/absence and adversarial atom class."""
import os
from pathlib import Path

from eoo_ir.coverage import expected, missing, new_table, observe, render_table
from eoo_ir.validate import validate

from oracle_util import sample_packages

N = 2000


def test_two_thousand_generated_packages_cover_the_ir():
    pkgs = sample_packages(N, 1)
    assert len(pkgs) == N
    table = new_table()
    for p in pkgs:
        assert validate(p) == []
        observe(p, table)
    print("\n" + render_table(table))
    if os.environ.get("H15_COVERAGE_OUT"):  # the verify script asks for the table as evidence
        Path(os.environ["H15_COVERAGE_OUT"]).write_text(render_table(table) + "\n")
    assert not missing(table), missing(table)
    assert set(expected()) <= set(table)


def test_coverage_checker_has_teeth():
    """Known-negative: an empty sample must report everything missing; a trivial package must not cover all."""
    t = new_table()
    assert set(missing(t)) == set(expected())
    observe({"package_id": "p", "version": "v", **{k: [] for k in (
        "object_types", "link_types", "interfaces", "functions", "actions", "policies", "authority_rules",
        "observation_types", "constraints")}}, t)
    assert missing(t)
