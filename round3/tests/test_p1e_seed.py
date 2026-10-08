import pytest

from r3_shared.clock import LogicalClock
from r3_shared.world import WorldStore

SEED_WRITERS = frozenset({"harness-seed", "svc"})


def _batches(tag):
    return [[{"op": "create", "type": "Part", "key": "P1", "props": {"v": tag}},
             {"op": "create", "type": "Part", "key": "P2", "props": {"v": tag + "!"}}],
            [{"op": "link", "link_type": "L", "src": "Part:P1", "dst": "Part:P2"}],
            [{"op": "update", "type": "Part", "key": "P1", "props": {"v": tag + "?"}}]]


def _world(tmp_path, name, batches, writers=SEED_WRITERS):
    clock = LogicalClock()
    st = WorldStore(tmp_path / name, clock=clock, writers=writers)
    seqs = st.seed(batches)
    return st, seqs


def _shape(st):
    return [(r["seq"], r["tx"], r["tag"], r["tick"], r["writer"], r["kind"], r["ref"]) for r in st.reader().log()]


def test_equal_shape_pairs_have_identical_schedule_and_aa(tmp_path):
    a, sa = _world(tmp_path, "a.db", _batches("secret-1"))
    b, sb = _world(tmp_path, "b.db", _batches("other-22"))
    c, sc = _world(tmp_path, "c.db", _batches("secret-1"))
    assert _shape(a) == _shape(b) == _shape(c) and sa == sb == sc
    assert [r["data"] for r in a.reader().log()] != [r["data"] for r in b.reader().log()]  # protected facts DO differ
    assert [r["data"] for r in a.reader().log()] == [r["data"] for r in c.reader().log()]  # A/A identical


def test_one_seed_mark_per_batch_and_tag(tmp_path):
    st, seqs = _world(tmp_path, "w.db", _batches("x"))
    log = st.reader().log()
    marks = [r for r in log if r["kind"] == "mark"]
    assert [m["ref"] for m in marks] == ["seed"] * 3 and [m["seq"] for m in marks] == seqs
    assert [m["data"] for m in marks] == [{"batch": 0, "changes": 2}, {"batch": 1, "changes": 1}, {"batch": 2, "changes": 1}]
    assert {r["tag"] for r in log} == {"seed"} and {r["writer"] for r in log} == {"harness-seed"}
    assert len({r["tx"] for r in log}) == 3
    snap = st.reader().snapshot()
    assert snap["objects"]["Part:P1"]["props"] == {"v": "x?"} and snap["links"] == [["L", "Part:P1", "Part:P2"]]


def test_seed_writer_must_be_allowlisted(tmp_path):
    st = WorldStore(tmp_path / "n.db", clock=LogicalClock(), writers=frozenset({"svc"}))
    with pytest.raises(ValueError, match="allowlist"):
        st.seed(_batches("x"))
    assert st.reader().log() == []


def test_unknown_change_op_rolls_back_the_batch(tmp_path):
    st = WorldStore(tmp_path / "r.db", clock=LogicalClock(), writers=SEED_WRITERS)
    with pytest.raises(ValueError, match="unknown seed change"):
        st.seed([[{"op": "create", "type": "Part", "key": "P1", "props": {}}, {"op": "explode"}]])
    assert st.reader().snapshot()["objects"] == {} and st.reader().log() == []


def test_different_shapes_give_different_schedules(tmp_path):
    a, _ = _world(tmp_path, "a.db", _batches("x"))
    b, _ = _world(tmp_path, "b.db", _batches("x")[:2])
    assert _shape(a) != _shape(b)
