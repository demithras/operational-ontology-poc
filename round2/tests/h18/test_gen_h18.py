"""Generator: deterministic, unique, reaches every required class, and the oracle replay classifies hostile ops as illegal."""
import random

import pytest

from eoo_h18 import corpus, gen
from eoo_h18.rig import EooRig


@pytest.fixture(scope="module")
def base(reader):
    from domains.project.seed_from_repo import build_seed
    return build_seed(reader)


def _cases(base, seed, n):
    rnd = random.Random(seed)
    return [gen.gen_case(rnd, base["ops"], base["head_commit"]) for _ in range(n)]


def test_same_seed_same_corpus_different_seed_different(base):
    a, b, c = (_cases(base, s, 40) for s in (1, 1, 2))
    assert [gen.case_hash(x) for x in a] == [gen.case_hash(x) for x in b] != [gen.case_hash(x) for x in c]


def test_3000_cases_are_nearly_all_unique_and_cover_every_required_class(base):
    cs = _cases(base, 18, 3000)
    assert len({gen.case_hash(c) for c in cs}) >= 2900
    seen = {}
    for c in cs:
        for r in gen.replay_classes(c):
            for k in r["classes"]:
                seen[k] = seen.get(k, 0) + 1
    assert [k for k in corpus.REQUIRED_CLASSES if not seen.get(k)] == []
    assert all(seen[k] > 20 for k in corpus.CORE_CLASSES), {k: seen[k] for k in corpus.CORE_CLASSES}


def test_hostile_classes_are_illegal_per_oracle_when_classified_so(base):
    for c in _cases(base, 4, 400):
        for r in gen.replay_classes(c):
            if {"post_freeze_threshold_edit", "forced_verdict", "evidence_wrong_version", "evidence_unpinned", "supersede_self",
                    "supersede_non_evaluated", "flag_non_orphan", "blank_freeze", "start_out_of_order"} & set(r["classes"]):
                assert r["legal"] is False, r


def test_rows_use_the_oracle_on_every_step_and_hash_ignores_facts(base):
    c = _cases(base, 3, 1)[0]
    d = {**c, "facts": {}}
    assert gen.case_hash(c) == gen.case_hash(d) and len(gen.replay_classes(c)) == len(c["ops"])
