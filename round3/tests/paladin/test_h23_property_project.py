"""Project-domain property: random call sequences by every project principal never commit an effect the (independent)
authority oracle of test_h23_property does not allow; lifecycle preconditions are checked against the live world."""
import tempfile
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from paladin_rig import Rig
from test_h23_property import oracle_allows, resources_of

WHO = ["researcher-1", "researcher-2", "viewer-1", "admin-1", "agent-evidence-1", "agent-draft-1"]
H = ["H-A", "H-B", "H-C", "H-D", "H-E", "H-NOPE"]
OPS = {
    "create_hypothesis": st.fixed_dictionaries({"claim": st.sampled_from(["c1", "c2", "", "ephemeral: x"])}),
    "preregister_hypothesis": st.fixed_dictionaries({"hypothesis": st.sampled_from(H), "freeze_hash": st.sampled_from(["f" * 64, ""])}),
    "start_run": st.fixed_dictionaries({"hypothesis": st.sampled_from(H)}),
    "evaluate_hypothesis": st.fixed_dictionaries({"hypothesis": st.sampled_from(H)}),
    "flag_orphan_component": st.fixed_dictionaries({"component": st.sampled_from(["cmp-live", "cmp-orphan", "cmp-x"])}),
    "attach_evidence": st.fixed_dictionaries({"hypothesis": st.sampled_from(H), "evidence": st.sampled_from(["EV-C1", "EV-C2", "EV-X"])}),
}
step = st.tuples(st.sampled_from(WHO), st.sampled_from(sorted(OPS)), st.data(), st.sampled_from(["a", "b", "c", "d"]),
                 st.sampled_from(["tool", "direct"]))


@settings(max_examples=40, deadline=None, derandomize=True, suppress_health_check=list(HealthCheck))
@given(st.lists(step, min_size=1, max_size=7))
def test_project_effects_are_always_authorized_and_once_per_request_id(steps):
    rig = Rig(Path(tempfile.mkdtemp()), "project")
    committed = set()
    for who, op, data, rid, via in steps:
        args = data.draw(OPS[op])
        f = rig.dep.call_tool if via == "tool" else rig.dep.direct
        res, eff = rig.effects_of(lambda: f(rig.token(who), op, args, request_id=f"rid-{rid}"))
        if eff:
            assert res.status == "OK" and oracle_allows(rig.auth, who, None, op, resources_of(rig, op, args)), (who, op, args, eff)
            assert rid not in committed
            committed.add(rid)
        else:
            assert res.status != "OK" or "replayed" in res.body or res.body.get("state") in ("PENDING_APPROVAL", "RECONCILED_SUCCESS")
    snap = rig.snap()["objects"]
    assert all(h["props"]["phase"] in ("DRAFT", "PREREGISTERED", "RUNNING", "EVALUATED", "SUPERSEDED")
               for k, h in snap.items() if k.startswith("Hypothesis:"))
