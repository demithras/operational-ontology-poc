"""H19 evaluator: a known-positive is SUPPORTED; for EACH support / reject / inconclusive / invalid clause a known-negative flips it."""
import copy
import json
import shutil

import pytest

from eoo_exp import provenance as prov
from eoo_exp.util import canon, sha_text
from eoo_h19 import audit, storelevel
from eoo_h19.evaluate import evaluate

CLEAN = {"engine_diff": lambda p: []}
FILES = ["rebuild-hashes.json", "concurrency-state-machine.json", "canonical-change-audit.json", "historical-binding-results.json", "mutation-results.json"]


def vals(v):
    return {r["id"]: r["value"] for rows in v["predicates"].values() for r in rows}


def flipped(base, v):
    b, x = vals(base), vals(v)
    return sorted(k for k in b if b[k] != x[k])


def refresh_summaries(dst):
    """After an edit of rows, recompute every derived summary the way the harness does (so only the intended clause flips)."""
    cs = json.loads((dst / FILES[1]).read_text())
    ca = json.loads((dst / FILES[2]).read_text())
    hb = json.loads((dst / FILES[3]).read_text())
    cs["payload"]["tally"] = t = storelevel.tally({"scenarios": cs["payload"]["scenarios"]})
    cs["payload"]["class_counts"] = {c: t["classes"].get(c, 0) for c in cs["payload"]["required_classes"]}
    ca["payload"]["summary"] = s = audit.summarize(ca["payload"]["cases"])
    hb["payload"]["store_level"] = {k: t[k] for k in hb["payload"]["store_level"]}
    hb["payload"]["engine_level"] = {k: s[k] for k in hb["payload"]["engine_level"]}
    for name, rec in ((FILES[1], cs), (FILES[2], ca), (FILES[3], hb)):
        rec["payload_hash"] = sha_text(canon(rec["payload"]))
        prov.write(dst, name, rec)


@pytest.fixture(scope="module")
def positive_dir(small_run, tmp_path_factory):
    """Known-positive: the real small run, padded to 5,000 unique scenarios, with the numbers only a full run shows written in."""
    dst = tmp_path_factory.mktemp("h19pos") / "pos"
    shutil.copytree(small_run, dst)
    for f in FILES:
        rec = json.loads((dst / f).read_text())
        rec["harness_dirty"], rec["harness_dirty_paths"] = False, []  # a real dev run has a dirty tree; the authoritative one does not
        p = rec["payload"]
        if f == FILES[1]:
            rows = p["scenarios"]
            while len(rows) < 5000:
                r = copy.deepcopy(rows[len(rows) % 100])
                r["id"] = f"pad{len(rows):05d}"
                rows.append(r)
            for c in p["required_classes"]:
                if not any(c in r["classes"] for r in rows if r["classes"] and not r["id"].startswith("pad")):
                    rows[0]["classes"].append(c)
            p["corpus"]["unique_scenarios"] = 5000
        if f == FILES[4]:
            for m in p["mutants"]:
                m["killed"] = True
            p["controls"].update(clean=True, clean_after=True)
        rec["payload_hash"] = sha_text(canon(rec["payload"]))  # the edit above may change the payload (e.g. a mutant not killed in a tiny run)
        prov.write(dst, f, rec)
    refresh_summaries(dst)
    return dst


@pytest.fixture()
def edit(positive_dir, tmp_path):
    """edit(filename, fn, record_fn=None, drop=None, refresh=False) -> evidence dir where fn(payload) edited that file (hash refreshed)."""
    count = [0]

    def _edit(filename=None, fn=None, record_fn=None, drop=None, refresh=False):
        count[0] += 1
        dst = tmp_path / f"ev{count[0]}"
        shutil.copytree(positive_dir, dst)
        if drop:
            (dst / drop).unlink()
        if filename:
            rec = json.loads((dst / filename).read_text())
            if fn:
                fn(rec["payload"])
                rec["payload_hash"] = sha_text(canon(rec["payload"]))
            if record_fn:
                record_fn(rec)
            prov.write(dst, filename, rec)
        if refresh:
            refresh_summaries(dst)
        return dst
    return _edit


@pytest.fixture(scope="module")
def base(positive_dir):
    return evaluate(positive_dir, **CLEAN)


def test_known_positive_is_supported(base):
    v = vals(base)
    assert base["verdict"] == "SUPPORTED" and not base["problems"], (base["verdict"], base["problems"], {k: x for k, x in v.items() if x is not (k not in ("R", "I") and not k.startswith("V"))})
    assert all(v[k] is True for k in ("S1", "S2", "S3", "S3b", "S4", "S5")) and v["R"] is False and v["I"] is False and not any(v[k] for k in v if k.startswith("V"))


def test_S1_rebuild_inequality_rejects(base, edit):
    d = edit(FILES[0], lambda p: p["store_histories"].update(unequal_commits=1, equal_commits=p["store_histories"]["equal_commits"] - 1))
    v = evaluate(d, **CLEAN)
    assert v["verdict"] == "REJECTED" and flipped(base, v) == ["R", "S1"]


def test_S1_single_pass_or_missing_fsck_or_bijection_is_not_support(base, edit):
    for fn in (lambda p: p["engine_histories"].update(passes=1), lambda p: p["store_histories"].update(fsck_all_ok=False), lambda p: p["engine_histories"].update(hash_bijection_violations=2)):
        v = evaluate(edit(FILES[0], fn), **CLEAN)
        assert v["verdict"] != "SUPPORTED" and "S1" in flipped(base, v)


def test_S2_ontology_only_write_rejects(base, edit):
    def fn(p):
        s = next(s for c in p["cases"] for s in c["steps"] if s["acc"])
        s.update(ootw=1, one_commit=False, new_commits=0)
    v = evaluate(edit(FILES[2], fn, refresh=True), **CLEAN)
    assert v["verdict"] == "REJECTED" and {"S2", "R"} <= set(flipped(base, v))


def test_S2_projection_mismatch_is_split_brain(base, edit):
    v = evaluate(edit(FILES[2], lambda p: next(s for c in p["cases"] for s in c["steps"]).update(proj=0, ootw=1), refresh=True), **CLEAN)
    assert v["verdict"] == "REJECTED" and v["numbers"]["audit"]["projection_mismatches"] == 1


def test_S3_silent_lost_update_rejects(base, edit):
    def fn(p):
        w = next(w for r in p["scenarios"] for w in r["w"] if w["g"] == "ok")
        w["L"] = 1
    v = evaluate(edit(FILES[1], fn, refresh=True), **CLEAN)
    assert v["verdict"] == "REJECTED" and {"S3", "R"} <= set(flipped(base, v))


def test_S3_accepting_a_write_the_oracle_refuses_is_a_silent_overwrite(base, edit):
    def fn(p):
        w = next(w for r in p["scenarios"] for w in r["w"] if w["x"] == "conflict")
        w.update(g="ok", a=0)
    v = evaluate(edit(FILES[1], fn, refresh=True), **CLEAN)
    assert v["verdict"] == "REJECTED" and "S3" in flipped(base, v)


def test_S3b_oracle_disagreement_alone_is_inconclusive_not_support(base, edit):
    v = evaluate(edit(FILES[1], lambda p: next(w for r in p["scenarios"] for w in r["w"] if w["g"] == "ok").update(a=0), refresh=True), **CLEAN)
    assert v["verdict"] == "INCONCLUSIVE" and flipped(base, v) == ["S3b"]


def test_S3b_replay_divergence_and_ref_moved_on_refusal(base, edit):
    for fn in (lambda w: w.update(r="neq"), lambda w: w.update(ref_ok=0)):
        def edit_rows(p, fn=fn):
            fn(next(w for r in p["scenarios"] for w in r["w"] if w["g"] == "conflict"))
        v = evaluate(edit(FILES[1], edit_rows, refresh=True), **CLEAN)
        assert v["verdict"] == "INCONCLUSIVE" and flipped(base, v) == ["S3b"]


def test_S4_unpinned_store_binding_rejects(base, edit):
    v = evaluate(edit(FILES[1], lambda p: next(b for r in p["scenarios"] for b in r["binds"]).update(pinned=0), refresh=True), **CLEAN)
    assert v["verdict"] == "REJECTED" and {"S4", "R"} <= set(flipped(base, v))


def test_S4_accepted_rebinding_and_engine_binding_change_reject(base, edit):
    def rebound(p):
        w = next(w for r in p["scenarios"] for w in r["w"] if w["t"] == "rebind")
        w["rebound"] = 1
    assert evaluate(edit(FILES[1], rebound, refresh=True), **CLEAN)["verdict"] == "REJECTED"
    v = evaluate(edit(FILES[2], lambda p: next(b for c in p["cases"] for b in c["bindings"]).update(entries_same=0), refresh=True), **CLEAN)
    assert v["verdict"] == "REJECTED" and "S4" in flipped(base, v)


def test_S5_a_surviving_target_mutant_is_not_support(base, edit):
    def fn(p):
        next(m for m in p["mutants"] if m["id"].startswith("M2")).update(killed=False)
    v = evaluate(edit(FILES[4], fn), **CLEAN)
    assert v["verdict"] == "INCONCLUSIVE" and flipped(base, v) == ["S5"]


def test_S5_missing_target_mutant_is_not_support(base, edit):
    v = evaluate(edit(FILES[4], lambda p: p.update(mutants=[m for m in p["mutants"] if not m["id"].startswith("M3")])), **CLEAN)
    assert v["verdict"] != "SUPPORTED" and "S5" in flipped(base, v)


def test_I_too_few_unique_scenarios_is_inconclusive(base, edit):
    v = evaluate(edit(FILES[1], lambda p: p.update(scenarios=p["scenarios"][:4999]), refresh=True), **CLEAN)
    assert v["verdict"] == "INCONCLUSIVE" and flipped(base, v) == ["I"] and v["numbers"]["unique_scenarios"] == 4999


@pytest.mark.parametrize("cls", ["stale_base", "conflicting_concurrent", "compatible_concurrent", "historical_binding_after_change"])
def test_I_a_missing_class_is_inconclusive(base, edit, cls):
    def fn(p):
        for r in p["scenarios"]:
            r["classes"] = [c for c in r["classes"] if c != cls]
    v = evaluate(edit(FILES[1], fn, refresh=True), **CLEAN)
    assert v["verdict"] == "INCONCLUSIVE" and flipped(base, v) == ["I"]


def test_missing_or_corrupt_evidence_never_supports(edit):
    assert evaluate(edit(drop=FILES[3]), **CLEAN)["verdict"] == "INCONCLUSIVE"
    d = edit()
    (d / FILES[0]).write_text("{not json")
    v = evaluate(d, **CLEAN)
    assert v["verdict"] == "INCONCLUSIVE" and v["problems"]


def test_V1_changed_freeze_hash_is_invalid(base, edit):
    v = evaluate(edit(FILES[0], record_fn=lambda r: r.update(protocol_freeze_hash="0" * 64)), **CLEAN)
    assert v["verdict"] == "INVALID" and flipped(base, v) == ["V1"]


def test_V2_disagreeing_provenance_or_other_engine_version_is_invalid(base, edit):
    v = evaluate(edit(FILES[1], record_fn=lambda r: r.update(seed=999)), **CLEAN)
    assert v["verdict"] == "INVALID" and flipped(base, v) == ["V2"]
    v = evaluate(edit(FILES[2], record_fn=lambda r: r.update(engine_version="1.0")), **CLEAN)
    assert v["verdict"] == "INVALID" and flipped(base, v) == ["V2"]


def test_V3_engine_or_store_differs_from_tag_is_invalid(base, positive_dir):
    v = evaluate(positive_dir, engine_diff=lambda p: ["round2/src/eoo_engine_git/store.py"])
    assert v["verdict"] == "INVALID" and flipped(base, v) == ["V3"]


def test_V4_non_independent_oracle_is_invalid(base, edit):
    v = evaluate(edit(FILES[1], lambda p: p["oracle"]["import_audit"].update(independent=False, forbidden=["model.py: import eoo_engine"])), **CLEAN)
    assert v["verdict"] == "INVALID" and flipped(base, v) == ["V4"]


def test_V5_dirty_harness_at_run_time_is_invalid(base, edit):
    v = evaluate(edit(FILES[0], record_fn=lambda r: r.update(harness_dirty=True, harness_dirty_paths=["round2/src/eoo_h19/rebuild.py"])), **CLEAN)
    assert v["verdict"] == "INVALID" and flipped(base, v) == ["V5"]


def test_V6_selfcheck_failures_are_invalid(base, edit):
    v = evaluate(edit(FILES[4], lambda p: p["controls"].update(clean=False)), **CLEAN)
    assert v["verdict"] == "INVALID" and "V6" in flipped(base, v)
    v = evaluate(edit(FILES[1], lambda p: next(r for r in p["scenarios"]).update(exc="KeyError: x"), refresh=True), **CLEAN)
    assert v["verdict"] == "INVALID" and "V6" in flipped(base, v)
    v = evaluate(edit(FILES[1], lambda p: p["tally"].update(writes=1)), **CLEAN)  # a summary that disagrees with its rows
    assert v["verdict"] == "INVALID" and "V6" in flipped(base, v)
    v = evaluate(edit(FILES[0], record_fn=lambda r: r["harness_sha256"].update({next(iter(r["harness_sha256"])): "0" * 64})), **CLEAN)
    assert v["verdict"] == "INVALID" and "V6" in flipped(base, v)


def test_every_clause_has_a_named_negative_test():
    import re
    src = open(__file__).read()
    for c in ("S1", "S2", "S3", "S3b", "S4", "S5", "I", "V1", "V2", "V3", "V4", "V5", "V6"):
        assert re.search(rf"def test_{c}_", src), c
