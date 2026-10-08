"""G3-E2: seed-tagged transactions are setup, never a candidate effect; other untagged canonical writes are flagged."""
from r3_oracle.const_judge import judge
from r3_oracle.constitution import Constitution
from r3_shared.clock import LogicalClock
from r3_shared.opsspec import load_ops_spec
from r3_shared.world import WorldStore
import json


def _run(tmp_path, seeded):
    clock = LogicalClock()
    st = WorldStore(tmp_path / "w.db", clock=clock, writers=frozenset({"harness-seed", "svc"}))
    r = st.reader()
    snap0 = r.snapshot()
    if seeded:
        st.seed([[{"op": "create", "type": "Part", "key": "P1", "props": {"v": 1}}]])
    else:
        h = st.handle("svc")
        with h.transaction():
            h.create("Part", "P2", {"v": 2})
        h.close()
    auth = json.load(open("spec/authority/manufacturing.v3.json"))
    C0 = Constitution.from_docs(auth, None, load_ops_spec("manufacturing"))
    out = judge([], r.log(0), C0, snap0, r.snapshot(), frozenset({"harness-seed", "svc"}))
    return out["case_classes"]


def test_seed_transactions_are_not_unattributed_writes(tmp_path):
    assert _run(tmp_path, True) == []


def test_untagged_canonical_write_without_commit_is_flagged(tmp_path):
    cls = _run(tmp_path, False)
    assert "unattributed_write" in cls
