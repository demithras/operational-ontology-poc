"""P11: WAL world store; the meter classifies world-lock timeouts instead of crashing."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

import pytest

from r3_harness.h23 import concurrency, evaluator, mutation
from r3_harness.h23.corpus import load_specs, new_env
from r3_harness.h23.runner import run_variant
from r3_shared import world
from r3_shared.world import WorldLockTimeout, WorldStore
from tests.fakes.h23_fakes import FakeVariant, load

TH = json.loads((Path(__file__).resolve().parents[1] / "protocol" / "thresholds.json").read_text())


def _locked(self):
    raise sqlite3.OperationalError("database is locked")


def test_every_connection_is_wal_with_busy_timeout(tmp_path):
    st = WorldStore(tmp_path / "w.db")
    h, r = st.handle("w"), st.reader()
    for con in (h._con, r._con):
        assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert con.execute("PRAGMA busy_timeout").fetchone()[0] == world.BUSY_MS
    h.close(); r.close()


def test_reader_is_not_blocked_by_a_leaked_open_write_transaction(tmp_path):
    st = WorldStore(tmp_path / "w.db")
    leaker, r = st.handle("leaker"), st.reader()
    leaker._con.execute("BEGIN IMMEDIATE")  # leaked: never committed
    leaker.create("t", "k", {"a": 1})
    assert r.snapshot()["objects"] == {}  # readers see the last committed state, no 'database is locked'
    done = []
    t = threading.Thread(target=lambda: done.append(r.snapshot()), daemon=True)
    t.start(); t.join(5)
    assert done, "reader hung behind a leaked writer"


def test_reader_snapshot_raises_world_lock_timeout_after_the_bounded_wait(tmp_path, monkeypatch):
    st = WorldStore(tmp_path / "w.db")
    r = st.reader()
    monkeypatch.setattr(world, "READ_WAIT_S", 0.3)
    monkeypatch.setattr(world.WorldReader, "_snapshot", _locked)
    with pytest.raises(WorldLockTimeout):
        r.snapshot()
    assert not r._con.in_transaction  # no transaction left open by the failed read


def test_reader_does_not_swallow_non_lock_errors(tmp_path, monkeypatch):
    r = WorldStore(tmp_path / "w.db").reader()
    monkeypatch.setattr(world.WorldReader, "_snapshot",
                        lambda self: (_ for _ in ()).throw(sqlite3.OperationalError("no such table: x")))
    with pytest.raises(sqlite3.OperationalError):
        r.snapshot()


@pytest.fixture
def unreadable(monkeypatch):
    monkeypatch.setattr(world, "READ_WAIT_S", 0.2)
    monkeypatch.setattr(world.WorldReader, "_snapshot", _locked)


def test_env_call_classifies_world_lock_timeout_instead_of_crashing(unreadable):
    env = new_env(load("fake-correct"), "manufacturing", load_specs(), "p11")
    try:
        op = env.ops["operations"][0]["name"]
        sub = env.agents()[0]
        rec = env.call(rule="x", via="direct", token=env.token(sub), subject=sub, operation=op, args={})
        assert rec["classes"] == ["world_lock_timeout"] and rec["measured"] == [] and env.world_unreadable == 1
    finally:
        env.close()


def test_concurrency_scenario_is_classified_not_crashed(unreadable):
    rec = concurrency.scenario(load("fake-correct"), load_specs(), 1, 0)
    assert rec["classes"] == ["world_lock_timeout"]
    assert concurrency.summarise([rec])["world_lock_timeout"] == 1


def test_mutant_run_counts_a_lock_timeout_as_a_detection(unreadable, monkeypatch):
    monkeypatch.setattr(mutation, "CONC_N", 4)
    mut, first = mutation._counts(load("fake-correct", ["unsynchronized_commit"]), load_specs(),
                                  "unsynchronized_commit", 1, 1)
    assert mut["world_lock_timeout"] == 4 and first is not None
    assert all("world_lock_timeout" in v for v in mutation.EXPECT.values())


def test_unmutated_variant_with_unreadable_world_is_inconclusive_never_supported(tmp_path, monkeypatch):
    out = tmp_path / "v"
    run_variant(lambda m: load("fake-correct", m), "fake-correct", out, "exp-p11", 7, 60, mutation_sequences=40,
                concurrency_scenarios=32)
    good = evaluator.evaluate_variant(out, TH, "fake-correct", 50, 24)
    assert good["verdict"] == "SUPPORTED", good["reasons"]
    # same evidence, but one raw call row recorded as unmeasurable: recomputed counts must drop SUPPORTED
    seq = out / "adversarial-sequences.jsonl"
    lines = seq.read_text().splitlines()
    rec = json.loads(lines[0])
    rec["calls"][0]["classes"].append("world_lock_timeout")
    lines[0] = json.dumps(rec, sort_keys=True, separators=(",", ":"))
    seq.write_text("\n".join(lines) + "\n")
    env = json.loads((out / "envelope.json").read_text())
    import hashlib
    env["raw_observations"]["evidence_sha256"][seq.name] = hashlib.sha256(seq.read_bytes()).hexdigest()
    (out / "envelope.json").write_text(json.dumps(env))
    summ = json.loads((out / "effect-oracle-diff.json").read_text())
    summ["class_counts"]["world_lock_timeout"] = 1
    (out / "effect-oracle-diff.json").write_text(json.dumps(summ))
    v = evaluator.evaluate_variant(out, TH, "fake-correct", 50, 24)
    assert v["verdict"] != "SUPPORTED"
    assert any("world unreadable 1 times" in r for r in v["reasons"]), v["reasons"]
