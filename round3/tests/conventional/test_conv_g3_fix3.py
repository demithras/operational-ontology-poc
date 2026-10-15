"""G3 fix3: G3-E22 effect_digest redaction (own decisions included); args_digest keeps the own exemption."""
import pytest

from conv_g3_util import make_g3
from conventional.lowprov import LowProv
from conventional.lowview import LowView

PL = "planner-1"
XFER = {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": "PX-17", "quantity": 10}


@pytest.fixture
def r(tmp_path):
    return make_g3(tmp_path, "hierarchical", governance=None, sub="", history=True)


def _tx_of_update(r, ref, props):
    """One autocommit world transaction updating `props` of `ref`; returns (handle, tx id)."""
    t, k = ref.split(":", 1)
    h = r.store.handle("seed")
    h.update(t, k, props)
    tx = h._con.execute("SELECT MAX(tx) FROM world_log WHERE kind!='mark'").fetchone()[0]
    return h, tx


def _lv(ref, fields):
    lv = LowView()
    lv.vis.add(ref)
    lv.fields[ref] = set(fields)
    return lv


def test_write_touching_a_hidden_field_is_redacted(r):
    ref = "WorkOrder:WO-43"
    h, tx = _tx_of_update(r, ref, {"plannedStart": 99})
    try:
        assert not LowProv._effect_low(h, _lv(ref, {"status", "priority"}), {"tx": tx})  # plannedStart/plannedFinish/... are outside the low view
        assert not LowProv._effect_low(h, LowView(), {"tx": tx})  # the object itself is hidden
    finally:
        h.close()


def test_write_touching_only_visible_fields_keeps_true_digest(r):
    ref = "WorkOrder:WO-43"
    h, tx = _tx_of_update(r, ref, {"plannedStart": 99})
    try:
        assert LowProv._effect_low(h, _lv(ref, {"plannedStart", "plannedFinish", "priority", "status", "workOrderId"}), {"tx": tx})
        assert LowProv._effect_low(h, LowView(), {"tx": None})  # nothing committed: the digest covers no row
    finally:
        h.close()


def test_own_external_write_is_redacted_but_args_digest_stays_true(r):
    assert r.dep.direct(r.token(PL), "transfer_inventory", XFER, None, "tx1").status == "OK"
    dec = r.dep.prov_decision(r.token(PL), "tx1").body["decision"]
    # the own write's effect rows (external WMS row) are not objects in the observer's low view -> redacted
    assert dec["effect_digest"] == {"redacted": "digest"}
    assert isinstance(dec["args_digest"], str) and len(dec["args_digest"]) == 64
