import sqlite3
import pytest
from r3_shared.world import WorldStore, WorldConflict, diff


@pytest.fixture
def store(tmp_path):
    return WorldStore(tmp_path / "w.db")


def test_write_through_handle_visible_to_reader(store):
    h, r = store.handle("svc"), store.reader()
    h.create("Part", "P1", {"unit": "each"})
    h.link("PartReferencing_part", "Lot:L1", "Part:P1")
    h.external_write("WMS", "transfer", {"q": 1}, "k1")
    s = r.snapshot()
    assert s["objects"]["Part:P1"] == {"props": {"unit": "each"}, "version": 1}
    assert s["links"] == [["PartReferencing_part", "Lot:L1", "Part:P1"]]
    assert s["effects"][0]["writer"] == "svc" and s["effects"][0]["idempotency_key"] == "k1"


def test_reader_cannot_write(store):
    r = store.reader()
    with pytest.raises(sqlite3.OperationalError):
        r._con.execute("INSERT INTO canonical_objects VALUES('X','y','{}',1)")


def test_update_versions_and_conflicts(store):
    h = store.handle("svc")
    h.create("Part", "P1", {"a": 1})
    assert h.update("Part", "P1", {"b": 2}, expected_version=1) == 2
    with pytest.raises(WorldConflict):
        h.update("Part", "P1", {"b": 3}, expected_version=1)
    with pytest.raises(WorldConflict):
        h.create("Part", "P1", {})
    with pytest.raises(WorldConflict):
        h.delete("Part", "NOPE")


def test_diff_deterministic_and_complete(store):
    h, r = store.handle("svc"), store.reader()
    h.create("Part", "P1", {"a": 1})
    h.create("Part", "P2", {"a": 1})
    before = r.snapshot()
    h.create("Part", "P0", {"z": 1})
    h.update("Part", "P1", {"a": 2})
    h.delete("Part", "P2")
    h.link("L", "a", "b")
    h.external_write("ERP", "po", {"fee": 3})
    after = r.snapshot()
    d1, d2 = diff(before, after), diff(before, after)
    assert d1 == d2
    assert [e["kind"] for e in d1] == ["create", "update", "delete", "link", "external"]
    assert d1[1]["changes"] == {"a": [1, 2]}
    assert diff(after, after) == []


def test_transaction_rollback(store):
    h, r = store.handle("svc"), store.reader()
    with pytest.raises(RuntimeError):
        with h.transaction():
            h.create("Part", "P1", {})
            raise RuntimeError("boom")
    assert r.snapshot()["objects"] == {}
