"""G3 fix1: G3-E20 query args (bare keys, typed), absent-lot value, work_order_risk form, E-4 effect digest, ok reason."""
from r3_harness.h26.env import decision_rec
from r3_oracle import disclosure_reads as R, provenance as pv


class _LV:  # the two attributes expected_query reads
    def __init__(self, ops, objects):
        self.ops_spec, self._s = ops, {"objects": objects, "links": [], "log_head": 0, "effects": []}

    def snapshot(self):
        return self._s


def _ops():
    from r3_harness.h26.gen_pair import load
    return load("manufacturing")[0]


def test_query_bare_key_args_and_absent_lot_is_zero():
    lv = _LV(_ops(), {"InventoryLot:L1": {"props": {"onHand": 20, "reserved": 0}}})
    assert R.expected_query(lv, "available_quantity", {"lot": "L1"}) == ("OK", {"value": 20})
    assert R.expected_query(lv, "available_quantity", {"lot": "NOPE"}) == ("OK", {"value": 0})


def test_query_ill_typed_or_unknown_args_have_no_oracle_answer():
    lv = _LV(_ops(), {})
    assert R.expected_query(lv, "available_quantity", {"lot": 7}) is None
    assert R.expected_query(lv, "available_quantity", {"lot": "L1", "x": 1}) is None
    out = R.expected_query(lv, "work_order_risk", {"work_order": "W"})
    assert set(out[1]["value"]) == {"work_order_id", "shortage", "at_risk"}


def test_decision_rec_digest_is_over_world_log_rows_and_reason_ok():
    rows = [{"seq": 1, "tx": 1, "tag": "t", "tick": 0, "writer": "w", "kind": "mark", "ref": "commit", "data": {}}]
    ops = {"operations": []}
    rec = decision_rec(ops, "s", None, "op", {}, "r1", "OK", "ok", [{"kind": "create", "ref": "A:1", "props": {}}], rows, 1, 0)
    assert rec["scalars"]["effect_digest"] == pv.effect_digest(rows)
    assert rec["scalars"]["reason"] == "ok"
    assert rec["scalars"]["effect_digest"] != pv.effect_digest(rec["effects"])
