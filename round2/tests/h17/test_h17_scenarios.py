"""Every scenario realises exactly the gate tokens it declares (a mis-declared token would be a harness bug, not a finding)."""
import pytest

from eoo_h17.drivers import MFG_LATER, new_driver
from eoo_h17.scenarios import ALL, PROFILES, for_profile

CASES = [(d, p, s.id) for d in ALL for p in PROFILES[d] for s in for_profile(d, p)]
GATE = {"fresh": "stale"}


def failing_token(scn):
    for g in ("identity", "request", "inputs", "fresh", "authority", "preconditions"):
        if not scn.tokens[g]:
            return GATE.get(g, g)
    return "policy" if scn.tokens["policy"] == "deny" else None


@pytest.mark.parametrize("domain,profile,sid", CASES)
def test_scenario_realises_its_declared_tokens(domain, profile, sid):
    scn = next(s for s in for_profile(domain, profile) if s.id == sid)
    drv = new_driver(domain, profile)
    if scn.clock:
        drv.clock["now"] = MFG_LATER
    before = drv.marker()
    rec = drv.engine.propose(scn.action, scn.inputs, scn.principal, idempotency_key="k1" if scn.key else None,
                             expected_versions=scn.expected_versions)
    failed = [g["gate"] for g in rec["gates"] if not g["passed"]]
    after = drv.marker()
    want = failing_token(scn)
    if want:
        assert failed == [want] and rec["state"] == "DENIED" and after == before
    elif scn.tokens["policy"] == "approval":
        assert rec["state"] == "PENDING_APPROVAL" and not failed and after == before
    else:
        assert rec["state"] == "RECONCILED_SUCCESS" and not failed
        assert after["effect_log"] == before["effect_log"] + scn.n_effects and after["external"] == before["external"] + scn.n_effects
        assert after["store"] == before["store"]


def test_both_domains_have_every_scenario_kind_they_can_have():
    for d in ALL:
        kinds = {s.kind for s in ALL[d]}
        assert {"ok", "unauthorized", "invalid"} <= kinds
    assert "approval" in {s.kind for s in ALL["manufacturing"]}


def test_every_ok_scenario_with_alt_inputs_has_a_different_intent():
    for d in ALL:
        for s in ALL[d]:
            if s.alt_inputs is not None:
                assert s.alt_inputs != s.inputs
