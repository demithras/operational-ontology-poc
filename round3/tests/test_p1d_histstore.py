import threading
import pytest
from r3_shared.histstore import HistoryStore, TamperView


def test_roundtrip_overwrite_delete_prefix_order(tmp_path):
    h = HistoryStore(str(tmp_path / "h.db"))
    assert h.get("a") is None and h.keys() == []
    for k in ("env/2", "env/1", "art/x", "env_x/9", "e%v/1"):
        h.put(k, k.encode())
    assert h.keys("env/") == ["env/1", "env/2"]          # prefix is literal: '_' and '%' do not act as wildcards
    assert h.keys("e%") == ["e%v/1"] and h.keys("env_") == ["env_x/9"]
    assert h.keys() == sorted(h.keys())
    h.put("env/1", b"new")
    assert h.get("env/1") == b"new"
    h.delete("env/1")
    h.delete("env/1")  # deleting a missing key is a no-op
    assert h.get("env/1") is None
    with pytest.raises(TypeError):
        h.put("k", "not-bytes")


def test_tamper_view_sees_and_changes_same_file_and_logs_every_primitive(tmp_path):
    p = str(tmp_path / "h.db")
    h, t = HistoryStore(p), TamperView(p)
    h.put("env/1", b"one")
    h.put("env/2", b"two")
    assert t.keys("env/") == ["env/1", "env/2"] and t.read("env/1") == b"one"
    t.write("env/1", b"EVIL")
    assert h.get("env/1") == b"EVIL"                     # variant sees the tamper (it is a mutable store)
    t.delete("env/2")
    assert h.get("env/2") is None
    t.rename("env/1", "env/9")
    assert h.get("env/9") == b"EVIL" and h.get("env/1") is None
    with pytest.raises(KeyError):
        t.rename("nope", "x")
    assert [x["op"] for x in t.log()] == ["write", "delete", "rename"]  # failed rename is not logged
    assert t.log()[1] == {"op": "delete", "key": "env/2", "existed": True}
    t.log().clear()
    assert len(t.log()) == 3                             # log() returns a copy


def test_thread_safe_puts(tmp_path):
    h = HistoryStore(str(tmp_path / "h.db"))
    ts = [threading.Thread(target=lambda i=i: [h.put(f"k/{i}/{j}", b"x") for j in range(50)]) for i in range(8)]
    [x.start() for x in ts]
    [x.join() for x in ts]
    assert len(h.keys("k/")) == 400
