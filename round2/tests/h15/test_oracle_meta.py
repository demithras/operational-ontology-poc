"""Meta-test of the oracle itself: inject known defects into the normalizer and prove the self-tests notice.

Two defect families: over-normalizing (merges things that differ -> false 'equivalent', caught by the mutation
sweep) and under-normalizing (fails to merge allowed rewrites -> false 'different', caught by the rewrite check).
"""
import copy

import pytest

import eoo_ir.equivalence as eq
import importlib

nm = importlib.import_module("eoo_ir.normalize")  # the package re-exports a function named 'normalize'
from eoo_ir.normalize import jkey, normalize as real_normalize
from eoo_ir.rewrites import rewrite

from oracle_util import sample_packages, sweep_mutations


def _per_action(f):
    def wrap(p):
        p = real_normalize(p)
        for a in p.get("actions", []):
            f(a)
        return p
    return wrap


def sort_effects(a):
    a["effects"].sort(key=jkey)


def sort_inputs(a):
    a["inputs"].sort(key=jkey)


def dedupe_preconditions(a):
    a["preconditions"] = sorted(set(a["preconditions"]))


def fill_compensation(a):
    a.setdefault("compensation_action", None)


def _top(f):
    def wrap(p):
        p = real_normalize(p)
        f(p)
        return p
    return wrap


def drop_metadata(p):
    p.pop("metadata", None)


def drop_descriptions(p):
    for o in p["object_types"]:
        o.pop("description", None)


def star_is_big_int(p):  # infers cardinality: "*" == 1000000
    for lk in p["link_types"]:
        for w in ("from_cardinality", "to_cardinality"):
            if lk[w]["max"] == "*":
                lk[w]["max"] = 10**6


def drop_version(p):
    for a in p["actions"]:
        a["version"] = ""


def functions_become_actions(p):  # collapse Function/Action kind: compare by id only
    ids = sorted([f["id"] for f in p["functions"]] + [a["id"] for a in p["actions"]])
    p["functions"], p["actions"] = [], []
    p["__ids__"] = ids


OVER = {
    "sort_effects": _per_action(sort_effects), "sort_inputs": _per_action(sort_inputs),
    "dedupe_preconditions": _per_action(dedupe_preconditions), "fill_compensation": _per_action(fill_compensation),
    "drop_metadata": _top(drop_metadata), "drop_descriptions": _top(drop_descriptions),
    "star_is_big_int": _top(star_is_big_int), "drop_version": _per_action(lambda a: a.update(version="")),
    "function_action_collapse": _top(functions_become_actions),
}


@pytest.mark.parametrize("bug", sorted(OVER))
def test_over_normalizing_defect_is_caught_by_the_mutation_sweep(bug, monkeypatch):
    monkeypatch.setattr(eq, "normalize", OVER[bug])
    stats = sweep_mutations(sample_packages(150)[:70], eq.equivalent, seeds=(1,))
    missed = [c for c, s in stats.items() if s["equiv_missed"]]
    assert missed, f"defect {bug} slipped past every mutation class"


def _noop(*_a, **_k):
    return None


def _no_property_sort(d, key):
    v = d.get(key)
    if isinstance(v, list):
        d[key] = [nm._property(q) for q in v]


UNDER = {  # (attribute of eoo_ir.normalize, replacement)
    "no_default_expansion": ("_default", _noop),
    "no_set_list_sorting": ("_sort_set", _noop),
    "no_property_sorting": ("_properties", _no_property_sort),
}


@pytest.mark.parametrize("bug", sorted(UNDER))
def test_under_normalizing_defect_is_caught_by_the_rewrite_check(bug, monkeypatch):
    attr, repl = UNDER[bug]
    monkeypatch.setattr(nm, attr, repl)
    failures = sum(1 for i, pkg in enumerate(sample_packages(150)) if not eq.equivalent(pkg, rewrite(pkg, i)).ok)
    assert failures > 0, f"defect {bug} slipped past the allowed-rewrite check"


def test_identity_normalizer_is_caught_by_the_rewrite_check(monkeypatch):
    monkeypatch.setattr(eq, "normalize", lambda p: copy.deepcopy(p))
    assert any(not eq.equivalent(p, rewrite(p, i)).ok for i, p in enumerate(sample_packages(150)))
