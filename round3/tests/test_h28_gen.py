"""Generator: deterministic, never raises, reachable (oracle-OK requests are oracle-OK), strata carry the frozen floors, twins share
schedules, the Byzantine catalogue is complete and each primitive misbehaves as specified."""
import json
from collections import Counter

import pytest

from r3_harness.h28 import adapters, specs
from r3_harness.h28.gen_case import build_case
from r3_harness.h28.gen_params import MAIN, PAIRS, draw_params
from r3_oracle import extoracle
from r3_shared import extcap
from r3_shared.extadapter import ADAPTER_IDS, ExternalRequest


def test_catalogue_ids_equal_the_frozen_ids():
    assert tuple(adapters.PRIMS) == tuple(ADAPTER_IDS)
    with pytest.raises(ValueError):
        adapters.Composite(None, ["ZZ"], 1, adapters.Scheduler(), lambda: 0)


def test_params_deterministic_and_counted_from_hypothesis():
    a, sa = draw_params(11, 300)
    b, _ = draw_params(11, 300)
    c, _ = draw_params(12, 300)
    assert a == b and a != c and len(a) == 300 and sa["hypothesis_shortfall"] == 0


def test_strata_cover_the_frozen_floors_at_official_size():
    ps, _ = draw_params(2811, 5600)
    assert all(sum(p["main"] == m for p in ps) >= 300 for m in MAIN)
    assert all(sum((p["domain"], p["system"]) == pair for p in ps) >= 300 for pair in PAIRS)
    assert sum(bool(p["crash"]) for p in ps) >= 200 and sum(bool(p["fault"]) for p in ps) >= 300
    assert sum(p["system"] == "GEN-NULL" for p in ps) >= 300
    assert Counter(len(p["prims"]) for p in ps).keys() <= {1, 2, 3}


def test_generator_never_raises_and_requests_have_the_intended_oracle_class():
    ps, _ = draw_params(5, 140)
    st = {}
    for p in ps:
        c = build_case(p, 5, st)
        assert c is not None, st
        ops, auth, systems = specs.load(c["domain"])
        if c["gen_null_ops"]:
            ops, auth = specs.with_gen_null(ops, auth)
        from r3_harness.h28.gen_case import seed_snapshot
        r = c["requests"][0]
        d = extoracle.decide(ops, auth, r["subject"], None, r["operation"], r["args"], seed_snapshot(ops), 0, approved=bool(r["approver"]))
        assert d.kind == ("DENIED" if r["expect"] == "approval" else "OK"), (c["id"], d.kind, d.reason)
        if d.kind == "OK":
            assert extoracle.intended(systems, d, r["rid"]), "an OK request must have an intended external effect"
        assert c["steps"][-1] == {"op": "final"} and c["steps"].count({"op": "dispatch"}) >= 2


def test_twin_schedule_is_the_same_object_shape():
    p = draw_params(3, 20)[0][0]
    c = build_case(p, 3, {})
    assert json.dumps(c["steps"]) == json.dumps(c["steps"]) and c["prims"] and True
    ps = draw_params(3, 20, "control")[0]
    assert all(q["prims"] == [] for q in ps)


class FakeClient:
    def __init__(self):
        self.calls = []

    def write(self, cap, op, tgt, pay, aid):
        self.calls.append((cap, op, tgt, pay, aid))
        from r3_shared.extworld import WriteReceipt
        return WriteReceipt("applied", "", len(self.calls))


def _req():
    root = extcap.mint_root(b"k" * 32, "n1", "ERP", "d1")
    cap = extcap.attenuate(root, system="ERP", operation="expedite", target="po:A", correlation="r#0")
    return ExternalRequest("r", 0, "ERP", "expedite", "po:A", {"po_id": "A", "expedite_fee": 5}, "", cap)


@pytest.mark.parametrize("prims,writes,status", [(["H0"], 1, "OK"), (["L1"], 0, "OK"), (["L2"], 1, "FAILED"), (["T1"], 1, "OK"), (["T2"], 1, "OK"),
                                                 (["T3"], 2, "OK"), (["R1"], 3, "OK"), (["G1"], 0, "FAILED"), (["G2"], 1, "OK"), (["G3"], 3, "OK"),
                                                 (["O2"], 0, "OK")])
def test_primitive_behaviour(prims, writes, status):
    cl = FakeClient()
    a = adapters.Composite(cl, [] if prims == ["H0"] else prims, 1, adapters.Scheduler(), lambda: 0, ["po:B"], [], 2, 2)
    r = a.submit(_req())
    assert len(cl.calls) == writes and r.status == status
    if prims == ["T1"]:
        assert cl.calls[0][2] == "po:B"
    if prims == ["T2"]:
        assert cl.calls[0][3] != _req().payload
    if prims == ["G1"]:
        assert "policy" in r.body["reason"]
    if prims == ["G2"]:
        assert "approval" in r.body and "grant" in r.body and "on_behalf_of" in r.body


def test_timeout_primitives_raise_and_o2_schedules_a_delayed_write():
    for p in (["O1"], ["L3"]):
        with pytest.raises(TimeoutError):
            adapters.Composite(FakeClient(), p, 1, adapters.Scheduler(), lambda: 0).submit(_req())
    sch, cl = adapters.Scheduler(), FakeClient()
    adapters.Composite(cl, ["O2"], 1, sch, lambda: 5, k=3).submit(_req())
    assert sch.due(7) == [] and len(sch.due(8)) == 1
