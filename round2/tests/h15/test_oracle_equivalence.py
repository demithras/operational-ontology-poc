"""Oracle self-tests: allowed rewrites are equivalent; every mutation class is detected."""
from hypothesis import given, strategies as st

from eoo_ir import equivalent, normalize, validate
from eoo_ir.mutations import REGISTRY, single_mutation
from eoo_ir.rewrites import allowed_rewrite
from eoo_ir.strategies import valid_packages

from oracle_util import sample_packages, sweep_mutations


@given(st.data())
def test_allowed_rewrite_is_equivalent(data):
    pkg = data.draw(valid_packages())
    rw = data.draw(allowed_rewrite(pkg))
    res = equivalent(pkg, rw)
    assert res.ok, res.diffs
    assert validate(rw) == []  # a rewrite keeps the package valid
    assert normalize(pkg) == normalize(rw)


@given(st.data())
def test_rewrites_of_rewrites_still_equivalent(data):
    pkg = data.draw(valid_packages())
    a, b = data.draw(allowed_rewrite(pkg)), data.draw(allowed_rewrite(pkg))
    assert equivalent(a, b).ok


@given(st.data())
def test_single_mutation_is_not_equivalent(data):
    pkg = data.draw(valid_packages())
    cid, mutated = data.draw(single_mutation(pkg))
    res = equivalent(pkg, mutated)
    assert not res.ok, f"mutation class {cid} judged equivalent"
    assert any(f in d for d in res.diffs for f in REGISTRY[cid].field.split("|")), (cid, res.diffs[:3])


def test_every_mutation_class_is_applicable_and_detected():
    stats = sweep_mutations(sample_packages(150), equivalent)
    never = [c for c, s in stats.items() if s["applied"] == 0]
    missed = {c: len(s["equiv_missed"]) for c, s in stats.items() if s["equiv_missed"]}
    wrong_field = {c: s["field_missed"][:1] for c, s in stats.items() if s["field_missed"]}
    assert not never, f"mutation classes never applicable in the sample: {never}"
    assert not missed, f"mutations the oracle judged equivalent: {missed}"
    assert not wrong_field, f"diffs did not name the mutated field: {wrong_field}"
    print(f"\n{len(stats)} mutation classes, {sum(s['applied'] for s in stats.values())} applications, 0 missed")


def test_oracle_notes_table_lists_exactly_the_mutation_classes():
    import re
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / "ontology" / "h15_oracle_notes.md").read_text()
    listed = set(re.findall(r"^\| `([a-z0-9_]+)` \| [a-z_]+ \| `", text, flags=re.M))
    assert listed == set(REGISTRY), (listed ^ set(REGISTRY))
