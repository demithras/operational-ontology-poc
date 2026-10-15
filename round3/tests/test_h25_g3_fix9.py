"""G3 fix9: the hierarchical model reaches refusal class already_judged; evaluator coverage self-check (absent class -> INCONCLUSIVE)."""
import collections
import gzip
import json
from pathlib import Path

import pytest

from r3_harness.h25 import analyze as AN
from r3_harness.h25 import evaluator as EV
from r3_harness.h25.gen_case import run_case, run_nogov
from r3_harness.h25.gen_race import TYPES, run_race
from r3_harness.h25.runner import write_evidence
from tests.h25_util import fake, small_pipeline

TH = json.loads((Path(__file__).resolve().parents[1] / "protocol" / "thresholds.json").read_text())
SEEDS = (2501, 2510)
N_CASES = 800


def _reasons_by_model(seed):
    v = fake("fake-honest")
    per = {m: collections.Counter() for m in AN.MODELS}

    def take(r):
        for t in r["tags"]:
            m = AN.TAG.match(t)
            if m and r["model"] in per:
                per[r["model"]][m.group(3)] += 1
        if "request:DENIED:case_required" in r["tags"] and r["model"] in per:
            per[r["model"]]["case_required"] += 1

    for i in range(N_CASES):
        take(run_case(v, seed, i))
    for j in range(40):
        take(run_race(v, seed, j, TYPES[j % len(TYPES)]))
    for k in range(10):
        take(run_nogov(v, seed, k))
    return per


@pytest.mark.parametrize("seed", SEEDS)
def test_every_model_reaches_every_reachable_refusal_class(seed):
    per = _reasons_by_model(seed)
    for m in AN.MODELS:
        missing = sorted(set(AN.reachable(m)["reasons"]) - set(per[m]))
        print(f"seed {seed} {m}: already_judged={per[m]['already_judged']}")  # reported counts
        assert per[m]["already_judged"] > 0, (seed, m)
        assert not missing, (seed, m, missing)


@pytest.fixture(scope="module")
def honest(tmp_path_factory):
    root = tmp_path_factory.mktemp("h25fix9")
    return small_pipeline("fake-honest", root, exp="exp-h25-dev-fix9", cases=140, races=14) / "fake-honest"


def _strip(honest, tmp_path, model, reason):
    d = tmp_path / "strip"
    d.mkdir()
    suffix = f":{reason}"
    with gzip.open(honest / AN.CASES_FILE, "rt") as fh, gzip.open(d / AN.CASES_FILE, "wt") as out:
        for line in fh:
            c = json.loads(line)
            if c["model"] == model:
                c["tags"] = [t for t in c["tags"] if not t.endswith(suffix)]
            out.write(json.dumps(c, sort_keys=True) + "\n")
    load = lambda f: json.loads((honest / f).read_text())  # noqa: E731
    write_evidence(d, "x", "exp-h25-dev", 1, 1, 1, 0, load(AN.FILES[4]), load(AN.FILES[2]), load(AN.FILES[3]))
    return d


def test_coverage_self_check_flags_an_absent_reachable_class(honest, tmp_path):
    def uncovered(res, model):
        return [x for x in res["reasons"] if x.startswith(f"model {model}: uncovered")]

    # known-positive/control: the untouched corpus (dev-size, other classes may be thin) does NOT cite already_judged
    base = EV.evaluate_variant(honest, TH, "x")
    assert "already_judged" in AN.analyze(honest)["models"]["hierarchical"]["reasons"]
    assert not any("already_judged" in x for x in uncovered(base, "hierarchical")), base["reasons"]
    d = _strip(honest, tmp_path, "hierarchical", "already_judged")
    assert "already_judged" not in AN.analyze(d)["models"]["hierarchical"]["reasons"]
    r = EV.evaluate_variant(d, TH, "x")
    assert r["verdict"] == "INCONCLUSIVE", (r["verdict"], r["reasons"])
    assert any("already_judged" in x for x in uncovered(r, "hierarchical")), r["reasons"]
    assert not any("already_judged" in x for m in ("collegial", "polycentric") for x in uncovered(r, m))
