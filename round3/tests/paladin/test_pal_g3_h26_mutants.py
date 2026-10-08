"""H26 mutants (KNOWN["H26"]): each is killed by a divergent pair, a canary hit, a surface mismatch or a false-provenance row."""
import json

from g3_pairs import divergences, run_pair
from g3_rig import G3Rig
from r3_shared.authspec import allowed_operations

CANARY = ["cv-7a1c3e90", "cv-b22f4d17"]


def seed(r):
    return r.store.handle("seed")


def _exist(r, k):                       # world k=0: the probed hidden object EXISTS; world k=1: it does not
    seed(r).create("Failure", f"cv-x{2 - k}", {"id": f"cv-x{2 - k}"})


def test_existence_status_split(tmp_path):
    def hidden(r, k):                   # world 0: Component cv-x2 exists (hidden from viewer-1); world 1: it does not
        seed(r).create("Component", f"cv-x{2 - k}", {"id": f"cv-x{2 - k}"})
    probe = (("mutating-hidden", lambda r, tk: r.dep.direct(tk, "flag_orphan_component", {"component": "cv-x2"}, request_id="sp")),
             ("read-hidden", lambda r, tk: r.dep.read_object(tk, "Component:cv-x2")))
    clean = run_pair(tmp_path, hidden, extra=probe)
    assert divergences(clean) == []
    killed = divergences(run_pair(tmp_path, hidden, extra=probe, mutants=["existence_status_split"]))
    assert "read-hidden" in killed and "mutating-hidden" in killed


def test_error_detail_leak(tmp_path):
    def hidden(r, k):
        seed(r).update("Evidence", "EV-C1", {"environment": CANARY[k]})
    probe = (("leak", lambda r, tk: r.dep.direct(tk, "attach_evidence", {"hypothesis": "H-A", "evidence": "EV-C1"}, request_id="lk")),)
    clean = run_pair(tmp_path, hidden, who="researcher-2", extra=probe)
    assert divergences(clean) == [] and not any(c in json.dumps(clean) for c in CANARY)
    mut = run_pair(tmp_path, hidden, who="researcher-2", extra=probe, mutants=["error_detail_leak"])
    assert "leak" in divergences(mut) and any(c in json.dumps(mut) for c in CANARY)


def test_hidden_tool_schema(tmp_path):
    for who in ("viewer-1", "researcher-1", "agent-draft-1"):
        r = G3Rig(tmp_path)
        expect = set(allowed_operations(r.auth, who, [o["name"] for o in r.ops["operations"]]))
        assert {t.name for t in r.dep.tools(r.tok(who))} == expect
        m = G3Rig(tmp_path, mutants=["hidden_tool_schema"])
        listed = {t.name for t in m.dep.tools(m.tok(who))}
        assert listed == {o["name"] for o in m.ops["operations"]} and (listed != expect or who == "researcher-1")


def test_subscription_unfiltered(tmp_path):
    def hidden(r, k):
        seed(r).update("Component", "cmp-live", {"path": CANARY[k]})
    assert divergences(run_pair(tmp_path, hidden)) == []
    mut = run_pair(tmp_path, hidden, mutants=["subscription_unfiltered"])
    assert "poll" in divergences(mut) and CANARY[0] in json.dumps(mut)
