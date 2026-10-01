"""Fail-closed property of protocol/h15_ambiguity_classes.json for single-line deletion mutants:
compile(M) raises, or render(compile(M)) states exactly the statements of M (same lines with the same
atoms, up to address renaming and the order of the external-name declarations, which form a set) --
the compiler accepted M only because M fully determines what it compiles to."""
import pytest
from hypothesis import given, settings

from eoo_ir.strategies import valid_packages
from eoo_openpona import OpenPonaError, compile as op_compile, render

from openpona_util import canonical_doc, delete_line, load

FILES = ["tests/h15/openpona_coverage_ir.json", "ontology/examples/manufacturing-minimal.json",
         "ontology/examples/project-domain-minimal.json"]


def _deletions(ir) -> tuple[int, int]:
    text, rec = render(ir)
    raised = accepted = 0
    for k in range(1, len(text.splitlines()) + 1):
        mt, mr = delete_line(text, rec, k)
        try:
            out = op_compile(mt, mr)
        except OpenPonaError:
            raised += 1
            continue
        accepted += 1
        t2, r2 = render(out)
        assert canonical_doc(t2, r2) == canonical_doc(mt, mr), f"line {k} deleted: compile invented or lost something"
    return raised, accepted


@pytest.mark.parametrize("path", FILES)
def test_every_single_line_deletion_fails_closed(path):
    raised, accepted = _deletions(load(path))
    assert raised > 0 and accepted > 0  # both branches are exercised


@settings(max_examples=25)
@given(valid_packages())
def test_generated_single_line_deletions_fail_closed(pkg):
    _deletions(pkg)


def test_failclosed_check_has_teeth(monkeypatch):
    """Known-negative: a compiler that defaults a missing 'required' to true must be caught."""
    import eoo_openpona.ctx as ctx
    orig = ctx._C.one

    def defaulting(self, a, f, required=True):
        if f == "required" and not self.d.facts.get((a, f)):
            return True
        return orig(self, a, f, required)

    monkeypatch.setattr(ctx._C, "one", defaulting)
    with pytest.raises(AssertionError):
        _deletions(load("ontology/examples/manufacturing-minimal.json"))
