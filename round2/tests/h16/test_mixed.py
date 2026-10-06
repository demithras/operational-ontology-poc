"""Mixed-domain generation: Hypothesis property over the generator; known-negatives for the load / mix / rename checks."""
import copy
import json
from collections import Counter

from hypothesis import given, strategies as st

from eoo_exp.util import canon, load_oracle, sha_text
from eoo_h15.isolation import isolated_constants
from eoo_h16.gen import KINDS, build_mixed, imports_domain, origin_counts
from eoo_h16.loadcheck import load_case, rename_domain, rename_invariant
from eoo_h16.mixed import generate, mixes_both
from eoo_ir import validate

ORACLE = load_oracle("h16", "kernel_oracle")
SEEN: Counter = Counter()


@given(st.randoms(use_true_random=False))
def _property(rnd):
    pkg, meta = build_mixed(rnd)
    assert validate(pkg) == [] and ORACLE.legal(pkg)
    assert mixes_both(pkg, meta), (meta, origin_counts(pkg))
    r = load_case(pkg)
    assert r["loaded"] and r["sizes_match"], r
    SEEN[meta["variant"]] += 1
    SEEN["cross_link"] += bool(meta["cross_added"].get("link_types"))
    SEEN["imports"] += imports_domain(pkg) and meta["variant"] != "merged_local"


def test_generated_mixed_packages_validate_and_load():
    SEEN.clear()
    with isolated_constants():
        _property()
    assert SEEN["merged_local"] and SEEN["import_project"] and SEEN["import_manufacturing"], SEEN
    assert SEEN["cross_link"] > 50 and SEEN["imports"] > 20, SEEN


def test_batch_generation_counts_unique_cases_and_is_deterministic():
    a, b = generate(5, 40), generate(5, 40)
    assert a["unique_cases"] >= 40 and a["valid_loaded_mixed"] == a["unique_cases"] and a["failures"] == []
    assert a["corpus_hash"] == b["corpus_hash"] and len({c["sha"] for c in a["cases"]}) == a["unique_cases"]
    assert a["rename_checked"] > 0 and a["rename_invariant"] == a["rename_checked"]


def test_merged_package_holds_resources_of_both_real_domains_and_the_colliding_id():
    import random
    for s in range(200):
        pkg, meta = build_mixed(random.Random(s))
        if meta["variant"] == "merged_local":
            ids = {o["id"] for o in pkg["object_types"]}
            if "Decision" in ids and "ProjectDecision" in ids:
                return
    raise AssertionError("no merged package carried both Decision (manufacturing) and ProjectDecision (project)")


def test_known_negative_invalid_package_is_not_counted():
    import random
    pkg, meta = build_mixed(random.Random(1))
    bad = copy.deepcopy(pkg)
    bad["link_types"].append({"id": "dangling", "from": "NoSuchType", "to": "NoSuchType", "from_cardinality": {"min": 0, "max": "*"},
                              "to_cardinality": {"min": 0, "max": "*"}})
    assert validate(bad) and not ORACLE.legal(bad) and not load_case(bad)["loaded"]


def test_known_negative_foreign_kind_is_not_kernel():
    import random
    pkg, _ = build_mixed(random.Random(2))
    pkg["quantities"] = []
    assert ORACLE.package_kinds_outside_kernel(pkg) == ["quantities"] and not ORACLE.legal(pkg)


def test_known_negative_single_domain_package_does_not_mix():
    import random
    for s in range(100):
        pkg, meta = build_mixed(random.Random(s))
        if meta["variant"] == "merged_local":
            only = {**pkg, **{k: [r for r in pkg[k] if r["id"] in origin_ids_of(pkg, k, "project")] for k in KINDS}}
            assert origin_counts(only)["manufacturing"] == 0
            assert not mixes_both(only, meta)
            return


def origin_ids_of(pkg, kind, dom):
    from eoo_h16.gen import origin_ids
    return origin_ids(dom)[kind]


def test_rename_invariance_known_positive_and_known_negative():
    import random
    from unittest import mock
    from eoo_h16 import mutants as M
    pkg = json.loads(open(__import__("eoo_exp.util", fromlist=["ROOT"]).ROOT.joinpath("domains/manufacturing/ir.json")).read())
    assert rename_invariant(pkg)["invariant"] is True
    with M.runtime_domain_branch():
        assert rename_invariant(pkg)["invariant"] is False
    assert rename_domain(pkg, "z")["package_id"] == "renamed-z" and pkg["package_id"] == "manufacturing-ontology"
