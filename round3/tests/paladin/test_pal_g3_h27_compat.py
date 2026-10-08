"""Gate 3 on top of Gate 2 provenance: governed effects are anchored decisions that replay VERIFIED; constitutional actions and
the case_required refusal do not break the history/anchor path (Q10)."""
import pytest

from g2_rig import new_anchor
from g3_rig import G3Rig
from r3_shared.histstore import HistoryStore


@pytest.fixture
def anchor(tmp_path_factory):
    ap = new_anchor(tmp_path_factory.mktemp("anchor"))
    yield ap
    ap.close()


def test_governed_execute_replays_verified_and_refusals_are_governed_decisions(tmp_path, anchor):
    r = G3Rig(tmp_path, v3=True, history=HistoryStore(str(tmp_path / "h.sqlite")), anchor=anchor.client())
    refused = r.dep.direct(r.tok("researcher-1"), "evaluate_hypothesis", {"hypothesis": "H-C"}, request_id="n1")
    assert refused.body == {"reason": "case_required"}
    assert r.dep.replay("n1").status == "VERIFIED"                                   # a refusal is a governed decision (reason case_required)
    r.propose("researcher-1", "c1", "evaluate_hypothesis", {"hypothesis": "H-C"})
    r.judge("admin-1", "c1", "concur")
    r.adv(5)
    res = r.act("researcher-1", "execute", case="c1", rid="ex1")
    assert res.status == "OK" and r.dep.replay("ex1").status == "VERIFIED"
    r.dep.crash()
    r.dep.restart()                                                                   # cases and the stored result come back from marks + history
    assert r.dep.case_state("c1")["executed"] is True
    again = r.act("researcher-1", "execute", case="c1", rid="ex2")
    assert (again.status, again.body) == (res.status, res.body)
