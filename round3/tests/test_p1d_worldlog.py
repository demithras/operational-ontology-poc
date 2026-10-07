import threading
import pytest
from r3_shared.clock import LogicalClock
from r3_shared.world import WorldStore, WorldConflict


def test_one_row_per_write_with_autocommit_tx_and_null_tag(tmp_path):
    clock = LogicalClock(5)
    st = WorldStore(tmp_path / "w.db", clock=clock)
    h, r = st.handle("svc"), st.reader()
    h.create("Part", "P1", {"a": 1})
    h.update("Part", "P1", {"b": 2})
    h.link("L", "x", "y")
    h.unlink("L", "x", "y")
    h.external_write("ERP", "po", {"q": 1}, "k")
    h.delete("Part", "P1")
    log = r.log()
    assert [x["kind"] for x in log] == ["create", "update", "link", "unlink", "external", "delete"]
    assert len({x["tx"] for x in log}) == 6 and all(x["tag"] is None and x["tick"] == 5 for x in log)
    assert log[1]["data"]["props"] == {"a": 1, "b": 2} and log[1]["data"]["version"] == 2
    assert log[4]["data"]["idempotency_key"] == "k" and all(x["writer"] == "svc" for x in log)
    assert r.snapshot()["log_head"] == log[-1]["seq"]
    assert r.log(after_seq=log[2]["seq"]) == log[3:]


def test_tx_groups_rows_with_tag_tick_and_marks(tmp_path):
    st = WorldStore(tmp_path / "w.db", clock=LogicalClock(3))
    h, r = st.handle("svc"), st.reader()
    with h.transaction(tag="effect") as tx:
        h.create("Part", "P1", {})
        s = tx.mark("commit", {"request_id": "r1", "kind": "call_tool", "authority_version": "v"})
        h.update("Part", "P1", {"a": 1})
    log = r.log()
    assert len({x["tx"] for x in log}) == 1 and {x["tag"] for x in log} == {"effect"}
    assert [x["kind"] for x in log] == ["create", "mark", "update"] and log[1]["seq"] == s and log[1]["ref"] == "commit"
    assert log[1]["data"]["request_id"] == "r1" and tx.id == log[0]["tx"]
    with pytest.raises(RuntimeError):
        tx.mark("x", {})  # closed
    with h.transaction() as t2:
        with pytest.raises(RuntimeError):
            with h.transaction():
                pass
    assert t2.id > tx.id


def test_rollback_leaves_no_log_rows(tmp_path):
    st = WorldStore(tmp_path / "w.db")
    h, r = st.handle("svc"), st.reader()
    with pytest.raises(WorldConflict):
        with h.transaction("t"):
            h.create("Part", "P1", {})
            h.create("Part", "P1", {})
    assert r.log() == [] and r.snapshot()["objects"] == {} and r.snapshot()["log_head"] == 0


def test_tx_tick_stable_while_clock_advances_mid_transaction(tmp_path):
    clock = LogicalClock(10)
    h = WorldStore(tmp_path / "w.db", clock=clock).handle("svc")
    with h.transaction() as tx:
        h.create("A", "1", {})
        threading.Thread(target=lambda: clock.advance(5)).start()
        for _ in range(100):
            if clock.now() == 15:
                break
        h.create("A", "2", {})
    assert clock.now() == 15 and tx.tick == 10
    assert {x["tick"] for x in WorldStore(tmp_path / "w.db").reader().log()} == {10}
    h2 = WorldStore(tmp_path / "w2.db").handle("svc")  # no clock -> tick 0
    with h2.transaction() as t0:
        pass
    assert t0.tick == 0


def test_writer_allowlist_refusal(tmp_path):
    st = WorldStore(tmp_path / "w.db", writers=frozenset({"a", "b"}))
    st.handle("a")
    with pytest.raises(ValueError, match="allowlist"):
        st.handle("evil")
    WorldStore(tmp_path / "w2.db").handle("anything")  # no allowlist = unrestricted (H23 behaviour)


def test_clock_is_thread_safe():
    clock = LogicalClock()
    ts = [threading.Thread(target=lambda: [clock.advance() for _ in range(500)]) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert clock.now() == 4000
