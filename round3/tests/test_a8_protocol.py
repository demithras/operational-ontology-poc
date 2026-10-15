"""PROT-H23-A8 protocol conformance on the fakes (the correct fake and the deliberately broken volatile-ledger fake)."""
import inspect
import threading

import pytest
from r3_shared import mutants
from r3_shared.clock import LogicalClock
from r3_shared.identity import IdentityProvider
from r3_shared.variant import Deployment, Variant
from r3_shared.world import WorldStore
from tests.fakes.fake_variant import FakeVariant, FakeVolatileVariant


def _setup(tmp_path, variant):
    clock, idp, store = LogicalClock(), IdentityProvider("secret-secret"), WorldStore(tmp_path / "w.db")
    sd = tmp_path / "state"
    sd.mkdir()
    dep = variant.deploy("manufacturing", store.handle_factory(), idp.verifier(), {}, {}, clock, state_dir=str(sd))
    return dep, idp.issue("alice", "fake", 10, clock), store.reader()


def _n(reader, key="P1"):
    return reader.snapshot()


def _put(dep, tok, key, rid):
    return dep.call_tool(tok, "put", {"type": "Part", "key": key}, request_id=rid)


def _version(reader, key="P1"):
    snap = reader.snapshot()
    return str(sorted(map(str, snap.items())))


def test_protocol_signature_and_known_mutants():
    assert "state_dir" in inspect.signature(Variant.deploy).parameters
    assert callable(Deployment.arm_crash)
    assert {"ledger_after_commit_volatile", "unsynchronized_commit"} <= set(mutants.KNOWN["H23"])
    assert mutants.validate(["unsynchronized_commit"])


def test_arm_crash_before_commit_zero_effects_then_unavailable_then_restart(tmp_path):
    dep, tok, reader = _setup(tmp_path, FakeVariant())
    before = _version(reader)
    dep.arm_crash("before_commit")
    r = _put(dep, tok, "P1", "r1")
    assert (r.status, r.body["reason"]) == ("UNKNOWN", "crashed")
    assert _version(reader) == before
    r = _put(dep, tok, "P1", "r2")
    assert (r.status, r.body["reason"]) == ("UNAVAILABLE", "crashed")
    dep.restart()
    assert _put(dep, tok, "P1", "r1").status == "OK"  # never committed, so this is a fresh request
    assert dep.read(tok, "get", {"type": "Part", "key": "P1"}).body["props"]["n"] == 1


def test_arm_crash_after_commit_exactly_one_effect_and_replay_is_idempotent(tmp_path):
    dep, tok, reader = _setup(tmp_path, FakeVariant())
    dep.arm_crash("after_commit")
    assert _put(dep, tok, "P1", "r1").status == "UNKNOWN"
    assert dep.read(tok, "get", {"type": "Part", "key": "P1"}).status == "OK"  # world holds the effect
    dep.restart()
    assert _put(dep, tok, "P1", "r1").status == "OK"  # same request_id: no additional effect
    assert dep.read(tok, "get", {"type": "Part", "key": "P1"}).body["props"]["n"] == 1
    assert _put(dep, tok, "P1", "r-new").status == "OK"  # NEW request_id is a new request
    assert dep.read(tok, "get", {"type": "Part", "key": "P1"}).body["props"]["n"] == 2


def test_crash_between_requests_then_restart(tmp_path):
    dep, tok, _ = _setup(tmp_path, FakeVariant())
    assert _put(dep, tok, "P1", "r1").status == "OK"
    dep.crash()
    assert _put(dep, tok, "P1", "r2").body["reason"] == "crashed"
    dep.restart()
    assert _put(dep, tok, "P1", "r1").status == "OK"
    assert dep.read(tok, "get", {"type": "Part", "key": "P1"}).body["props"]["n"] == 1


def test_broken_volatile_ledger_double_commits_after_after_commit_replay(tmp_path):
    dep, tok, _ = _setup(tmp_path, FakeVolatileVariant())
    dep.arm_crash("after_commit")
    assert _put(dep, tok, "P1", "r1").status == "UNKNOWN"
    dep.restart()
    _put(dep, tok, "P1", "r1")
    assert dep.read(tok, "get", {"type": "Part", "key": "P1"}).body["props"]["n"] == 2  # double commit (the defect)


def test_concurrent_callers_commit_each_request_id_once(tmp_path):
    dep, tok, _ = _setup(tmp_path, FakeVariant())
    results = []
    threads = [threading.Thread(target=lambda: results.append(_put(dep, tok, "P1", "same"))) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert [r.status for r in results] == ["OK"] * 8
    assert dep.read(tok, "get", {"type": "Part", "key": "P1"}).body["props"]["n"] == 1


def test_arm_crash_rejects_unknown_point(tmp_path):
    dep, _, _ = _setup(tmp_path, FakeVariant())
    with pytest.raises(ValueError):
        dep.arm_crash("midway")
