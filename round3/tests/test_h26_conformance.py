"""C26-1..C26-7 (ORACLE-AND-HARNESS-G3 C): generated edge cases run against BOTH real variants via the registry (and the
oracle-backed fake as the machinery self-test) and compared with the oracle's decisions. These may FAIL until the variant
builders land - a red row is information (which clause, which variant), not a harness bug. A variant that is not built yet
FAILS with its reason (never skipped)."""
import collections
import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from r3_harness.h26 import fuzz, gen_pair, observe
from r3_oracle import disclosure_reads as R, lowproj
from r3_shared.anchor import start_anchor
from r3_shared.registry import load_variant
from tests.fakes import fake_h26

ROOT = Path(__file__).resolve().parents[1]
N_PAIRS = 12
_cache: dict = {}


@pytest.fixture(scope="module", autouse=True)
def _anchor():
    """Ruling Q10: H26 worlds run WITH a HistoryStore + AnchorClient. When R3_ANCHOR_SOCK is unset start an anchor here
    (short /tmp path: unix socket length limit)."""
    if os.environ.get("R3_ANCHOR_SOCK"):
        yield
        return
    d = tempfile.mkdtemp(prefix="h26a-", dir="/tmp")
    ap = start_anchor(os.path.join(d, "anchor"), os.path.join(d, "s"))
    os.environ["R3_ANCHOR_SOCK"] = ap.sock_path
    _cache.clear()
    try:
        yield
    finally:
        os.environ.pop("R3_ANCHOR_SOCK", None)
        try:
            ap.close()
        finally:
            shutil.rmtree(d, ignore_errors=True)


def factory(name):  # noqa: D401
    if name == "fake":
        return fake_h26.H26Variant()
    try:
        return load_variant(name)
    except NotImplementedError as exc:
        pytest.fail(f"{name}: not implemented yet - G3 ({exc})")


def gather(name):
    """Run N_PAIRS pairs (world 0 and 1 and A/A) on a variant; returns tag counters + observations."""
    if name in _cache:
        return _cache[name]
    v = factory(name)
    try:
        return _gather(name, v)
    except NotImplementedError as exc:
        pytest.fail(f"{name}: {exc}")


def _gather(name, v):
    tags, labels, obs_pairs, aa = collections.Counter(), collections.Counter(), [], []
    for i in range(N_PAIRS):
        p, _ = gen_pair.draw(11, i)
        if p is None:
            continue
        runs = [observe.run_world(v, p, w) for w in (0, 1)]
        for r in runs:
            tags.update(t[2] for t in r["tags"])
            labels.update(r["labels"])
        obs_pairs.append((p, runs))
        q, _ = gen_pair.draw(11, i + 10 ** 6, aa=True)
        if q is not None:
            aa.append([observe.run_world(v, q, w)["obs"] for w in (0, 1)])
    _cache[name] = {"tags": tags, "labels": labels, "pairs": obs_pairs, "aa": aa}
    return _cache[name]


VARIANTS = ["fake", "paladin", "conventional"]


@pytest.mark.parametrize("name", VARIANTS)
def test_c26_1_tools_equal_oracle_set_and_schemas(name):
    g = gather(name)
    assert g["labels"].get("unsupported", 0) == 0, g["labels"]
    assert g["tags"].get("hidden_capability", 0) == 0 and g["tags"].get("schema_disclosure", 0) == 0
    assert g["tags"].get("exposure_loss", 0) == 0 and g["tags"].get("exposure_ok", 0) > 0


@pytest.mark.parametrize("name", VARIANTS)
def test_c26_2_every_low_method_returns_the_frozen_forms(name):
    g = gather(name)
    assert g["tags"].get("form_violation", 0) == 0 and g["labels"].get("variant_error", 0) == 0, (g["tags"], g["labels"])


@pytest.mark.parametrize("name", VARIANTS)
def test_c26_3_hidden_and_absent_twins_are_identical(name):
    out = fuzz.run(factory(name), 5, 400)
    assert out["unsupported"] == 0 and out["variant_error"] == 0, out
    assert out["existence_leak"] == [] and out["value_exfiltration"] == [] and out["twin_checks"] > 100


@pytest.mark.parametrize("name", VARIANTS)
def test_c26_4_reads_equal_the_low_view_answers(name):
    g = gather(name)
    assert g["tags"].get("read_mismatch", 0) == 0 and g["tags"].get("read_ok", 0) > 100, dict(g["tags"])


@pytest.mark.parametrize("name", VARIANTS)
def test_c26_5_same_world_twice_is_identical(name):
    g = gather(name)
    assert g["aa"] and all(a == b for a, b in g["aa"])


def test_c26_6_projection_known_negatives():
    a = lowproj.project("read_object", "OK", {"ref": "T:k", "props": {"x": 1}})
    assert lowproj.diff([a], [lowproj.project("read_object", "OK", {"ref": "T:k", "props": {"x": 2}})]) is not None
    r1, r2 = lowproj.Renamer(), lowproj.Renamer()
    assert lowproj.diff([lowproj.project("approve", "OK", {"decision_id": "a"}, r1)],
                        [lowproj.project("approve", "OK", {"decision_id": "b"}, r2)]) is None
    from r3_harness.h26 import evaluator
    assert callable(evaluator.evaluate_variant)  # an empty observation list cannot reach SUPPORTED: see test_h26_fakes missing-evidence


@pytest.mark.parametrize("name", VARIANTS)
def test_c26_7_provenance_views_equal_the_oracle_redacted_view(name):
    g = gather(name)
    bad = {k: v for k, v in g["tags"].items() if k.startswith(("false_provenance", "over_redaction", "provenance_overdisclosure"))}
    assert not bad and g["tags"].get("prov_ok", 0) > 10, (bad, dict(g["tags"]))


@pytest.mark.parametrize("name", ["fake", "paladin", "conventional"])
def test_c26_noninterference_on_the_conformance_pairs(name):
    g = gather(name)
    diverging = [p["id"] for p, runs in g["pairs"] if runs[0]["obs"] != runs[1]["obs"]]
    assert not diverging, diverging


_ = (json, ROOT, R)
