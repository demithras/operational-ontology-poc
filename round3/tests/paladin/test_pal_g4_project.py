"""Project overlay (Q2): publish_result (REGISTRY, full, at_most_once, approval for public) and notify_reviewer (NOTIFY,
effects_only, idempotent_set) run through the same generic seam; the approval rule stays in the decision plane."""
from g4_adapters import TargetSubstitution
from g4_rig import G4Rig, PUB

NOTE = {"hypothesis": "H-A", "reviewer": "rev-1"}


def test_publish_internal_commits_and_reconciles_with_full_confidence(tmp_path):
    r = G4Rig(tmp_path, "project")
    try:
        res = r.call("researcher-1", "publish_result", PUB, "p1")
        assert res.status == "OK" and res.body["outcomes"][0]["system"] == "REGISTRY"
        (o,) = r.settle("p1")
        assert (o["state"], o["confidence"]) == ("RECONCILED_SUCCESS", "full")
        (row,) = r.applied("p1#0")
        assert (row["system"], row["operation"], row["target"]) == ("REGISTRY", "publish", "registry:verdict-H-D-1")
    finally:
        r.finish()


def test_public_visibility_needs_a_second_principals_approval_and_the_adapter_cannot_supply_it(tmp_path):
    r = G4Rig(tmp_path, "project")
    try:
        pub = {**PUB, "visibility": "public"}
        res = r.call("researcher-1", "publish_result", pub, "p1")
        assert (res.status, res.body["reason"]) == ("DENIED", "approval_required") and r.dep.dispatch_pending().body == {"submitted": 0}
        assert r.dep.approve(r.token("researcher-1"), "publish_result", pub, "researcher-1").status == "DENIED"   # requester
        assert r.dep.approve(r.token("admin-1"), "publish_result", pub, "researcher-1").status == "OK"
        assert r.call("researcher-1", "publish_result", pub, "p2").status == "OK"
        assert r.settle("p2")[0]["state"] == "RECONCILED_SUCCESS"
    finally:
        r.finish()


def test_negative_bad_visibility_blank_visibility_and_unauthorised_caller_leave_zero_effects(tmp_path):
    r = G4Rig(tmp_path, "project")
    try:
        before = r.snap()
        got = [r.call("researcher-1", "publish_result", {**PUB, "visibility": "secret"}, "b1").status,     # deny rule
               r.call("researcher-1", "publish_result", {**PUB, "visibility": "  "}, "b2").status,          # deny rule first (G3-E17 order)
               r.call("viewer-1", "publish_result", PUB, "b3").status,                                      # no grant
               r.call("researcher-1", "publish_result", {**PUB, "verdict": "V-NOPE"}, "b4").status]         # absent target
        assert got == ["DENIED", "DENIED", "DENIED", "INVALID"]
        r.dep.dispatch_pending()
        assert r.snap() == before and r.ledger()["effects"] == [] and all(not x.log for x in r.recorders.values())
    finally:
        r.finish()


def test_notify_is_effects_only_low_confidence_idempotent_set(tmp_path):
    r = G4Rig(tmp_path, "project")
    try:
        assert r.call("researcher-1", "notify_reviewer", NOTE, "n1").status == "OK"
        (o,) = r.settle("n1")
        assert (o["system"], o["state"], o["confidence"]) == ("NOTIFY", "RECONCILED_SUCCESS", "low")
        assert r.applied("n1#0")[0]["target"] == "notify:rev-1"
    finally:
        r.finish()


def test_registry_target_substitution_is_detected_as_divergence(tmp_path):
    r = G4Rig(tmp_path, "project", per_system={"REGISTRY": TargetSubstitution})
    try:
        assert r.call("researcher-1", "publish_result", PUB, "p1").status == "OK"
        assert r.settle("p1")[0]["state"] == "DIVERGED" and r.applied("p1#0") == []
    finally:
        r.finish()
