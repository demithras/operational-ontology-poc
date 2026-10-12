"""R29-0/R29-1: lease-backed authority. Hand-written expectations from the frozen text (PROT-H29 s1.4, P1g-2)."""
import pytest

from conv_g5_util import TRANSFER, V0, make_g5, narrowed, stop_all
from r3_shared.authsvc import doc_digest


@pytest.fixture
def rig(tmp_path):
    r = make_g5(tmp_path / "r")
    yield r
    stop_all()


def test_decision_binds_the_leased_version(rig):
    res = rig.d("planner-1", "transfer_inventory", TRANSFER, "r1")
    assert res.status == "OK"
    used = rig.dep.authority_used("r1").body
    assert used["authority_version"] == doc_digest(V0)
    assert rig.dep.recovery_view()["committed"][0]["authority_version"] == doc_digest(V0)


def test_renew_on_every_decision_lease_log(rig):
    for i in range(3):
        rig.d("planner-1", "transfer_inventory", {**TRANSFER, "quantity": 1}, f"r{i}")
        rig.tick()
    log = rig.actl.log()
    assert len([x for x in log["leases"] if x["deployment"] == "dep-g5"]) >= 3   # one fetch per governed decision


def test_decides_inside_lease_window_during_outage(rig):
    rig.d("planner-1", "transfer_inventory", {**TRANSFER, "quantity": 1}, "r0")   # lease at tick 2, until 6
    rig.actl.outage("dep-g5", 3, 12)
    rig.tick()                                                                     # tick 3, AUTH down, lease valid
    assert rig.d("planner-1", "transfer_inventory", {**TRANSFER, "quantity": 1}, "r1").status == "OK"
    assert rig.dep.dependency_status()["AUTH"] == "DOWN"


def test_past_lease_until_is_unavailable_auth_never_last_known_good(rig):
    rig.d("planner-1", "transfer_inventory", {**TRANSFER, "quantity": 1}, "r0")   # lease [2, 6)
    rig.actl.outage("dep-g5", 3, 12)
    rig.tick(4)                                                                    # tick 6: lease_until is exclusive
    res = rig.d("planner-1", "transfer_inventory", {**TRANSFER, "quantity": 1}, "r1")
    assert (res.status, res.body) == ("UNAVAILABLE", {"reason": "dependency_unavailable", "dependency": "AUTH"})
    assert "r1" not in rig.commits()


def test_stale_sensitive_request_is_denied_after_publish_takes_effect(rig):
    rig.d("planner-1", "transfer_inventory", {**TRANSFER, "quantity": 1}, "r0")    # lease [2, 6) of V0
    info = rig.actl.publish_info(narrowed())
    assert info["effective_tick"] == 6                                              # waits for the outstanding lease
    rig.tick(4)                                                                     # tick 6: new version in force
    res = rig.d("planner-1", "transfer_inventory", {**TRANSFER, "quantity": 1}, "r1")
    assert (res.status, res.body["reason"]) == ("DENIED", "no_matching_allow")   # authority, not a business rule
    assert "r1" not in rig.commits()


def test_pending_publish_inside_old_lease_keeps_old_version(rig):
    rig.d("planner-1", "transfer_inventory", {**TRANSFER, "quantity": 1}, "r0")
    rig.actl.publish(narrowed())
    rig.tick()
    res = rig.d("planner-1", "transfer_inventory", {**TRANSFER, "quantity": 1}, "r1")   # tick 3 < f=6: V0 still in force
    assert res.status == "OK"
    assert rig.dep.authority_used("r1").body["authority_version"] == doc_digest(V0)


def test_adoption_is_recorded_in_the_world_and_durable(rig):
    rig.actl.publish(narrowed())
    rig.tick(4)
    rig.d("planner-1", "transfer_inventory", TRANSFER, "r1")
    marks = [x for x in rig.reader.log() if x["kind"] == "mark" and x["ref"] == "authority"]
    assert marks and marks[-1]["data"]["op"] == "adopt_lease"
    assert marks[-1]["data"]["base"] == doc_digest(narrowed())
