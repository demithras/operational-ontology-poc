"""H27 history generator, content-based discovery, tamper primitives, affected-set derivation and case runner,
exercised on the honest fake (anchor unsandboxed here: audit enforcement is tested end-to-end in test_h27_e2e.py)."""
import json
import random

import pytest

from r3_harness.h27 import base as base_mod
from r3_harness.h27 import case, corpus, layout, tamper
from r3_oracle import provenance as pv
from r3_shared.anchor import start_anchor
from r3_shared.histstore import TamperView
from tests.fakes import fake_h27


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    d = tmp_path_factory.mktemp("h27t")
    ap = start_anchor(d / "anchor", d / "sock")
    try:
        var = fake_h27.load("fake-h27-honest")
        bases = corpus.build_bases(var, ap.client(), str(d / "w"), 7, 2, (10, 14))
        yield {"var": var, "anchor": ap.client(), "bases": bases, "dir": d}
    finally:
        ap.close()


def run(env, b, classes, seed, tag):
    return case.run_case(env["bases"][b], env["var"], env["anchor"], str(env["dir"] / f"c-{tag}"), tag, seed, classes)


def test_bases_cover_both_domains_kinds_and_statuses(env):
    bs = env["bases"]
    assert {b.domain for b in bs} == {"manufacturing", "project"} and len(bs) == 4
    kinds = {d["kind"] for b in bs for d in b.decisions}
    statuses = {d["status"] for b in bs for d in b.decisions}
    assert {"call_tool", "direct"} <= kinds and "OK" in statuses and len(statuses) >= 2
    assert all(10 <= b.n for b in bs)
    assert all(not b.divergences and not b.unanchored for b in bs), [b.divergences[:2] for b in bs]


def test_every_base_has_a_committed_request_and_the_oracle_binding_matches_the_anchor(env):
    for b in env["bases"]:
        assert any(d["kind"] in ("call_tool", "direct") and d["status"] == "OK" and d["rows"] for d in b.decisions)
        for row in b.bundles:
            assert row["anchored_root"] == row["oracle_root"] == row["stored_root"]


def test_v2_histories_bind_delegate_and_revoke_with_null_policy_and_contract(env):
    kinds = [d["kind"] for b in env["bases"] for d in b.decisions]
    assert "delegate" in kinds
    for b in env["bases"]:
        for d in b.decisions:
            if d["kind"] in ("delegate", "revoke"):
                assert d["artifacts"]["policy"] == d["artifacts"]["contract"] == pv.NULL_DIGEST and d["artifacts"]["evidence"] == []


def test_envelopes_receipts_and_blobs_are_found_by_content_after_every_key_is_renamed(env, tmp_path):
    b = env["bases"][0]
    _, h = b.copy_to(str(tmp_path))
    v = TamperView(h)
    before = layout.scan(v)
    for i, k in enumerate(v.keys("")):
        v.rename(k, f"opaque/{i:05d}")
    after = layout.scan(v)
    assert sorted(after.envs) == sorted(before.envs) == list(range(1, b.n + 1))
    assert sorted(after.receipts) == sorted(before.receipts) and after.receipts
    assert set(after.blobs) == set(before.blobs) and b.all_digests() <= set(after.blobs)


def test_untouched_copy_has_no_affected_decisions_and_replays_verified(env, tmp_path):
    b = env["bases"][1]
    _, h = b.copy_to(str(tmp_path))
    v = TamperView(h)
    aff = tamper.derive(b, v)
    assert not aff["definite"] and not aff["indeterminate"] and len(aff["unaffected"]) == b.n


@pytest.mark.parametrize("cls", tamper.SINGLE)
def test_each_class_changes_something_and_the_honest_variant_detects_all_of_it(env, cls):
    applied = 0
    for b, seed in ((0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (1, 6)):
        r = run(env, b, [cls], seed + 100 * tamper.SINGLE.index(cls), f"{cls}-{b}-{seed}")
        assert r["classes_hit"] == [], (cls, r["classes_hit"], r["flags"])
        if r["applied"]:
            applied += 1
            assert r["definite"], (cls, r["flags"])
            for x in r["replays"]:
                if x["set"] == "definite":
                    assert x["replay"]["status"] in ("TAMPERED", "UNRESOLVED")
                elif x["set"] == "unaffected":
                    assert x["replay"]["status"] == "VERIFIED"
    assert applied >= 3, f"{cls} applied only {applied}/6 times"


def test_delete_envelope_makes_that_decision_definite_and_later_ones_indeterminate(env, tmp_path):
    b = env["bases"][0]
    _, h = b.copy_to(str(tmp_path))
    v = TamperView(h)
    for hit in layout.scan(v).envs[4]:
        v.delete(hit["key"])
    aff = tamper.derive(b, v)
    assert aff["definite"] == {4} and aff["indeterminate"] == set(range(5, b.n + 1)) and aff["unaffected"] == {1, 2, 3}


def test_reorder_relinks_a_self_consistent_chain_that_only_the_anchor_contradicts(env, tmp_path):
    b = env["bases"][0]
    _, h = b.copy_to(str(tmp_path))
    v = TamperView(h)
    ctx = {"flags": set()}
    assert tamper.t6(v, b, random.Random(3), ctx)
    sc = layout.scan(v)
    prev = pv.ZERO
    for s in range(1, b.n + 1):
        e = sc.env(s)
        assert e["seq"] == s and e["prev"] == prev      # the attacker's history verifies against itself
        prev = pv.root_of(e)
    roots = [row["anchored_root"] for row in b.bundles]
    assert [pv.root_of(sc.env(s)) for s in range(1, b.n + 1)] != roots


def test_rebind_replaces_a_digest_everywhere_and_relinks_later_prev_links(env, tmp_path):
    b = env["bases"][1]
    for seed in range(20):
        _, h = b.copy_to(str(tmp_path / f"r{seed}"))
        v = TamperView(h)
        ctx = {"flags": set()}
        if tamper.t5(v, b, random.Random(seed), ctx):
            break
    else:
        pytest.fail("no rebind applicable")
    sc = layout.scan(v)
    prev = pv.ZERO
    for s in range(1, b.n + 1):
        assert sc.env(s)["prev"] == prev
        prev = pv.root_of(sc.env(s))
    assert any(f.startswith("rebind") for f in ctx["flags"]) and tamper.derive(b, v)["definite"]


def test_forge_receipt_rewrites_stored_receipts_to_the_attackers_chain(env, tmp_path):
    b = env["bases"][2]
    for seed in range(30):
        _, h = b.copy_to(str(tmp_path / f"f{seed}"))
        v = TamperView(h)
        ctx = {"flags": set()}
        if tamper.t8(v, b, random.Random(seed), ctx):
            break
    sc = layout.scan(v)
    forged = [s for s, hits in sc.receipts.items() if hits[0]["entry"]["root"] == pv.root_of(sc.env(s))]
    anchored = {s: row["anchored_root"] for s, row in zip(range(1, b.n + 1), b.bundles)}
    assert forged and any(pv.root_of(sc.env(s)) != anchored[s] for s in forged) and "forge" in ctx["flags"]


def test_continuation_probe_on_the_honest_variant_has_no_effect_and_runs_once_per_base(env):
    r = run(env, 0, ["T9"], 11, "t9a")
    assert "continuation" in r["flags"] and r["continuation"]["probes"] and not r["continuation"]["violation"]
    assert r["classes_hit"] == []


def test_plan_has_all_classes_compound_share_and_one_t9_per_base():
    pl = corpus.plan(random.Random(1), 400, 40)
    cls = [c for c, _ in pl]
    assert {c[0] for c in cls if len(c) == 1} == set(tamper.CLASSES)
    assert sum(len(c) > 1 for c in cls) / len(cls) >= 0.25 and all(2 <= len(c) <= 4 for c in cls if len(c) > 1)
    t9 = [b for c, b in pl if c == ["T9"]]
    assert len(t9) == len(set(t9)) and not any("T9" in c for c in cls if len(c) > 1)


def test_clean_control_replays_every_decision_verified_and_artifacts_equal_the_expected_binding(env):
    r = run(env, 2, [], 5, "clean")
    assert len(r["replays"]) == env["bases"][2].n and r["classes_hit"] == []
    assert all(x["replay"]["status"] == "VERIFIED" for x in r["replays"])


def test_a_variant_that_ignores_the_anchor_is_caught_by_the_harness_not_by_the_variant(env, tmp_path):
    var = fake_h27.load("fake-h27-noanchor")
    bs = corpus.build_bases(var, env["anchor"], str(tmp_path / "w"), 3, 1, (8, 10), tag="na")
    assert any(b.unanchored for b in bs)                              # R27-6: OK decisions without an anchor entry
    assert all(row["anchored_root"] is None for b in bs for row in b.bundles)   # the anchor never saw them


def test_json_serialisable_case_record(env):
    r = run(env, 3, ["T1", "T4"], 9, "ser")
    json.dumps(r, default=str)


def test_run_effective_yields_exactly_n_effective_cases_and_counts_the_noops(env):
    stats = {}
    out = list(corpus.run_effective(env["var"], env["anchor"], env["bases"], str(env["dir"] / "eff"), 4, 25, stats))
    assert len(out) == 25 and all(corpus.effective(r) for r in out)
    assert stats["attempts"] == 25 + stats.get("noops", 0)
    assert {a for r in out for a in r["applied"]} >= {"T1", "T2", "T3", "T4", "T7"}


def test_a_moved_artifact_is_indeterminate_not_definite_and_not_a_false_alarm(env, tmp_path):
    """The bytes of a bound artifact survive under ANOTHER key: content-addressed lookup may find them, key lookup not."""
    b = env["bases"][1]
    _, h = b.copy_to(str(tmp_path))
    v = TamperView(h)
    sc = layout.scan(v)
    d = b.bound(1)[1][1]                       # the authority digest of decision 1
    key = sc.holders(d)[0]
    raw = v.read(key)
    v.write(key, b"{}")
    v.write("elsewhere/copy", raw)
    aff = tamper.derive(b, v)
    assert 1 in aff["indeterminate"] and 1 not in aff["definite"]


def test_a_digest_kept_in_a_sidecar_makes_its_decision_affected_when_the_sidecar_is_rewritten(env, tmp_path):
    """digest_omission shape: the policy digest sits in a record beside the envelope. Rewriting that record affects
    exactly its own decision (a VERIFIED replay of it is a tamper acceptance), not the others sharing the digest."""
    import copy
    b = env["bases"][1]
    _, h = b.copy_to(str(tmp_path))
    v = TamperView(h)
    pol = {s: dict(b.bound(s))["policy"] for s in (2, 3)}
    for s in (2, 3):
        v.write(f"side/{s:010d}", pol[s].encode())
    b2 = copy.copy(b)
    b2.sc = layout.scan(v)
    if hasattr(b2, "_bound_holders"):
        del b2._bound_holders
    assert not tamper.derive(b2, v)["definite"]                       # untouched sidecars: nothing affected
    other = next(d for d in sorted(b.all_digests()) if d != pol[3])
    v.write("side/%010d" % 3, other.encode())
    aff = tamper.derive(b2, v)
    assert 3 in aff["definite"] and 2 not in aff["definite"], aff
