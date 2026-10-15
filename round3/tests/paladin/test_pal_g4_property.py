"""Property test (derandomised, Q14): random request sequences x adapter primitives; the independent model below (hand-derived from
PROT-H28 s3/s4, not from the code) predicts every final state, and the ledger invariants hold for all of them."""
import pathlib
import tempfile

from hypothesis import HealthCheck, given, settings, strategies as st

from g4_adapters import Duplicate, FalseFailure, FalseSuccess, Honest, Omission, PayloadMutation, TargetSubstitution, TimeoutAfterApply
from g4_rig import BIGFEE, EXP, G4Rig
from r3_shared.extadapter import payload_digest

MODEL = {Honest: "RECONCILED_SUCCESS", FalseSuccess: "RECONCILED_FAILED", FalseFailure: "RECONCILED_SUCCESS",
         TimeoutAfterApply: "RECONCILED_SUCCESS", TargetSubstitution: "DIVERGED", PayloadMutation: "DIVERGED",
         Duplicate: "RECONCILED_SUCCESS", Omission: "RECONCILED_FAILED"}
REQ = st.sampled_from([("planner-1", EXP, "OK"), ("planner-1", {**EXP, "expedite_fee": 33}, "OK"), ("planner-1", BIGFEE, "DENIED"),
                       ("junior-1", EXP, "DENIED")])


@settings(max_examples=14, deadline=None, derandomize=True, database=None, suppress_health_check=list(HealthCheck))
@given(adapter=st.sampled_from(sorted(MODEL, key=lambda c: c.__name__)), reqs=st.lists(REQ, min_size=1, max_size=4),
       dispatches=st.integers(1, 3))
def test_final_state_and_ledger_invariants(adapter, reqs, dispatches):
    r = G4Rig(pathlib.Path(tempfile.mkdtemp(prefix="g4p")), adapter=adapter)
    try:
        ok = {}
        for i, (sub, args, want) in enumerate(reqs):
            rid = f"q{i}"
            res = r.call(sub, "expedite_purchase_order", args, rid)
            assert res.status == want, (rid, res)
            if want == "OK":
                ok[rid] = args
        for _ in range(dispatches):
            r.dep.dispatch_pending()
        for rid in ok:
            assert r.settle(rid)[0]["state"] == MODEL[adapter], (adapter.__name__, rid)
        rows, intended = r.ledger()["effects"], {f"{rid}#0": payload_digest(a) for rid, a in ok.items()}
        for row in rows:                                        # nothing outside scope, at most one row per at_most_once correlation
            assert intended.get(row["correlation"]) == row["payload_digest"] and row["target"] == "po:PO-992"
        assert len({x["correlation"] for x in rows}) == len(rows)
    finally:
        r.finish()
