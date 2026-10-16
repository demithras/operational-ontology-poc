"""H30 pilot repro M1: approval edge-issuer exclusion must be re-checked when the approval is CONSUMED.

Rule (author 2026-10-16, stricter reading of PROT-H24:67-68): the approver must not be Q or any issuer on any edge path from Q to
the requester that exists when the approval is consumed. K approves P(A) for R on behalf of Q before any Q..R path exists, then
delegates K->R under Q->K. R's request must be DENIED approval_required with no world change.
"""
import pytest

from conventional.variant import ConventionalVariant
from paladin.variant import PaladinVariant
from tests.h24_util import OP, base_spec, edge
from r3_harness.h23.corpus import load_specs
from r3_harness.h24.env import G2Env

APPR = "approval:expedite"
ARGS = {"po_id": "PO-991", "expedite_fee": 600}  # fee > 500 -> expedite-large-fee-needs-approval
# K = supervisor-1 holds approval:expedite STATICALLY (both variants decide the approver capability from base grants, not edges)
Q, K, R = "planner-1", "supervisor-1", "junior-1"


def _spec():
    return base_spec()


@pytest.mark.parametrize("name", ["paladin", "conventional"])
def test_m1_edge_issuer_approver_is_refused_at_consume(name):
    variant = PaladinVariant() if name == "paladin" else ConventionalVariant()
    ops, _ = load_specs()["manufacturing"]
    env = G2Env(variant, "manufacturing", ops, _spec(), f"m1-{name}")
    try:
        e1 = edge("e1", Q, K, None, ops=(OP,))
        e2 = edge("e2", K, R, "e1", ops=(OP,))
        assert env.delegate(e1, "d1")["status"] == "OK"
        # step 1: K approves P(A) for R obo Q while no Q..R path exists
        ap = env.approve(K, R, Q, OP, ARGS)
        assert ap.status == "OK", (ap.status, ap.body)  # precondition: the approval was recorded
        # step 2: K delegates K->R under Q->K
        assert env.delegate(e2, "d2")["status"] == "OK"  # precondition: the path Q->K->R now exists
        before = env.snapshot()
        head = before["log_head"]
        # step 3: R calls P(A) obo Q
        rec = env.request(R, Q, OP, ARGS, "r1")
        after = env.snapshot()
        written = env.reader.log(head)  # protected resource: world_log rows written by R's request (commit mark, effects)
        assert (rec["status"], rec["reason"]) == ("DENIED", "approval_required"), (rec["status"], rec["reason"], rec["body"])
        assert after["objects"] == before["objects"], "world rows changed although the request must be denied"
        assert written == [], f"world_log changed by a request that must be denied: {[(w['kind'], w['ref']) for w in written]}"
    finally:
        env.close()
