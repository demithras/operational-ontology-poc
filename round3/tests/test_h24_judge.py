"""H24 run judge: each class is produced by a minimal known-negative variant and by nothing else (known-positive: honest)."""
import sqlite3

import pytest

from r3_oracle import ops_model
from r3_shared.variant import CallResult
from tests.fakes import h24_fakes
from tests.fakes.h24_fakes import H24Dep, H24Variant, load
from tests.h24_util import ARGS, OP, classes, edge, judged, make_env, use


def chain(env, n=2):
    es = [edge("e1", "planner-1", "junior-1")]
    if n > 1:
        es.append(edge("e2", "junior-1", "senior-1", "e1"))
    for e in es:
        assert env.delegate(e, "d-" + e["id"])["status"] == "OK"
    return es


def run(name, fn, mutants=()):
    env = make_env(load(name, mutants))
    try:
        fn(env)
        return classes(env)
    finally:
        env.close()


def test_honest_chain_use_revoke_and_authority_used_are_all_ok():
    def go(env):
        chain(env)
        assert use(env, "u1", "senior-1")["status"] == "OK"
        env.authority_used("u1")
        env.revoke("planner-1", "e1", "v1")
        assert use(env, "u2", "senior-1")["status"] == "DENIED"
    cl, calls = run("fake-honest", go)
    assert cl == []
    assert [r["committed"] for r in calls.values()] == [True, True, True, False, True, False]
    assert calls[0]["must"] is True and calls[2]["must"] is True  # a legal delegation / use is a progress obligation
    assert calls[5]["must"] is False and calls[5]["classes"] == ["ok"]  # the refused post-revocation use is correct


def test_post_boundary_effect_from_a_stale_decision_cache():
    def go(env):
        chain(env, 1)
        use(env, "u1")
        env.revoke("planner-1", "e1", "v1")
        use(env, "u2")  # same (subject, obo, op, resources): the cache answers ALLOW after the revocation
    cl, calls = run("fake-stalecache", go)
    assert cl == ["post_boundary_effect"]
    assert calls[3]["classes"] == ["post_boundary_effect"] and calls[3]["committed"]


def test_forbidden_effect_not_post_boundary_when_the_path_was_never_valid():
    def go(env):
        assert env.delegate(edge("e1", "planner-1", "junior-1", keys=["PO-992"]), "d-e1")["status"] == "OK"
        wide = edge("x", "junior-1", "senior-1", "e1", keys=["PO-991"])  # a key the parent edge does not carry
        assert env.delegate(wide, "d-x")["status"] == "OK"  # the amplifier accepts it
        use(env, "u1", "senior-1")  # ... and uses only the LAST edge's scope
    cl, calls = run("fake-amplifier", go)
    assert "scope_amplification" in cl and "forbidden_effect" in cl and "post_boundary_effect" not in cl


def test_early_ack_is_a_linearizability_violation_and_unapplied_ack_is_flagged():
    def go(env):
        chain(env, 1)
        assert env.revoke("planner-1", "e1", "v1")["status"] == "OK"  # acknowledged, applied only after the next effect
        use(env, "u1")
        use(env, "u2")
    cl, calls = run("fake-earlyack", go)
    assert cl == ["linearizability_violation"]
    cl2, _ = run("fake-earlyack", lambda env: (chain(env, 1), env.revoke("planner-1", "e1", "v1")))
    assert cl2 == ["authority_ack_without_commit"]  # nothing ever applied the acknowledged revoke


def test_cycle_grant_and_inclusive_expiry_known_negatives():
    def cyc(env):
        chain(env)
        env.delegate(edge("c", "senior-1", "planner-1", "e2"), "d-c")
    assert run("fake-cyclegrant", cyc)[0] == ["cycle_grant"]

    def exp(env):
        assert env.delegate(edge("e1", "planner-1", "junior-1", exp=10), "d1")["status"] == "OK"
        env.advance(9)
        use(env, "u1")  # tick 9: usable
        env.advance(1)
        use(env, "u2")  # tick 10: NOT usable; the mutant accepts
    cl, calls = run("fake-inclusiveexpiry", exp)
    assert cl == ["post_boundary_effect"] and calls[2]["classes"] == ["ok"]


class Silent(H24Dep):  # revoke returns OK and never writes anything
    def revoke(self, token, edge_id, request_id):
        return CallResult("OK", {})


class DenyAll(H24Dep):
    def _decide(self, sub, obo, op, res, tick):
        from r3_oracle.authority_v2 import Decision
        return Decision(False, "no_valid_path", ())


class LiarUsed(H24Dep):
    def authority_used(self, request_id):
        r = super().authority_used(request_id)
        return CallResult(r.status, {**r.body, "path": ["e-wrong"]}) if r.status == "OK" else r


class Rogue(H24Dep):
    def _run_locked(self, token, op, args, obo, rid, backstop):
        self.world.create("Rogue", f"r{len(self.used)}", {"x": 1})  # canonical write outside any commit-marked transaction
        return super()._run_locked(token, op, args, obo, rid, backstop)


class Forgetful(H24Dep):  # the committed-request ledger is ignored: a replayed request_id commits a second time
    def _run_locked(self, token, op, args, obo, rid, backstop):
        self.results.clear()
        return super()._run_locked(token, op, args, obo, rid, backstop)


def custom(cls):
    class V(H24Variant):
        def deploy(self, domain, factory, verifier, ops, auth, clock, state_dir=None, history=None, anchor=None):
            return cls(domain, factory, verifier, ops, auth, clock, self.mutants, state_dir, self.quirks)
    return V(cls.__name__)


def runc(cls, fn):
    env = make_env(custom(cls))
    try:
        fn(env)
        return classes(env)
    finally:
        env.close()


def test_ack_without_commit_progress_loss_historical_mismatch_unattributed_duplicate():
    assert runc(Silent, lambda e: (chain(e, 1), e.revoke("planner-1", "e1", "v1")))[0] == ["authority_ack_without_commit"]
    assert runc(DenyAll, lambda e: (chain(e, 1), use(e, "u1")))[0] == ["progress_loss"]
    assert runc(LiarUsed, lambda e: (chain(e, 1), use(e, "u1"), e.authority_used("u1")))[0] == ["historical_mismatch"]
    cl, _ = runc(Rogue, lambda e: (chain(e, 1), use(e, "u1")))
    assert "unattributed_write" in cl
    cl, calls = runc(Forgetful, lambda e: (chain(e, 1), use(e, "u1"), use(e, "u1")))
    assert cl == ["forbidden_effect"] and calls[2]["classes"] == ["forbidden_effect"] and calls[1]["classes"] == ["ok"]


def test_unlogged_write_and_writer_violation_are_detected_from_the_world_itself():
    env = make_env(load("fake-honest"))
    try:
        chain(env, 1)
        con = sqlite3.connect(env.store.path)  # a direct SQL write that bypasses world_log
        con.execute("UPDATE canonical_objects SET props_json='{\"x\":1}' WHERE type='PurchaseOrder' AND key='PO-992'")
        con.commit()
        con.close()
        assert "unlogged_write" in classes(env)[0]
    finally:
        env.close()
    env = make_env(load("fake-honest"))
    try:
        env.store.writers = None
        h = env.store.handle("rogue-writer")
        h.external_write("ERP", "x", {"a": 1})
        h.close()
        cl = classes(env)[0]
        assert "writer_violation" in cl and "unattributed_write" in cl
    finally:
        env.close()


def test_unsupported_when_the_variant_lacks_the_g2_methods():
    class NoG2(H24Dep):
        delegate = revoke = authority_used = property(lambda self: None)
    env = make_env(custom(NoG2))
    try:
        r = env.delegate(edge("e1", "planner-1", "junior-1"), "d1")
        assert r["unsupported"] and "not implemented yet - G2" in r["reason"]
        assert "unsupported" in classes(env)[0]
    finally:
        env.close()


def test_progress_floor_flags_a_serializer_in_the_unrelated_subtree_probe():
    from r3_harness.h23.corpus import load_specs
    from r3_harness.h24.gen_race import run_race
    specs, v = load_specs(), load("fake-serializer")
    rows = [run_race(v, specs, 1, i, "UN") for i in range(0, 90, 9)]
    assert any("progress_loss" in r["classes"] for r in rows)
    ok = [run_race(load("fake-honest"), specs, 1, i, "UN") for i in range(0, 90, 9)]
    assert not any("progress_loss" in r["classes"] for r in ok)
    _ = ops_model, h24_fakes, judged, pytest, ARGS
