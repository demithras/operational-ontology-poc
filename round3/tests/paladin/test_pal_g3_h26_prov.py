"""H26 s4 provenance redaction (R26-5): true value or explicit marker, `partial` constant, own-only authority_used_as."""
import pytest

from g2_rig import new_anchor
from g3_rig import G3Rig
from r3_shared.disclosure import check_decision, is_marker, check_low_result
from r3_shared.histstore import HistoryStore

ATT = ("attach_evidence", {"hypothesis": "H-C", "evidence": "EV-C1"})


@pytest.fixture
def anchor(tmp_path_factory):
    ap = new_anchor(tmp_path_factory.mktemp("anchor"))
    yield ap
    ap.close()


@pytest.fixture
def rig(tmp_path, anchor):
    r = G3Rig(tmp_path, v3=True, history=HistoryStore(str(tmp_path / "h.sqlite")), anchor=anchor.client())
    r.res = r.dep.direct(r.tok("researcher-1"), *ATT, request_id="d1")
    return r


def test_own_view_is_true_and_complete(rig):
    res = rig.dep.prov_decision(rig.tok("researcher-1"), "d1")
    check_low_result("prov_decision", res)
    d = res.body["decision"]
    assert res.body["partial"] is True and d["subject"] == "researcher-1" and d["operation"] == "attach_evidence"
    assert d["status"] == rig.res.status and d["decision_id"] == "d1"
    assert not any(is_marker(v) for v in d.values() if not isinstance(v, list)) or d["effect_digest"] != d["args_digest"]


def test_foreign_low_view_redacts_actors_with_explicit_markers(rig):
    res = rig.dep.prov_decision(rig.tok("researcher-2"), "d1")        # Evidence is visible with provenance `scalars` only
    check_low_result("prov_decision", res)
    d = res.body["decision"]
    assert d["subject"] == {"redacted": "actor"} and d["on_behalf_of"] == {"redacted": "actor"}
    assert d["operation"] == "attach_evidence" and d["decision_id"] == "d1" and d["world_seq"] == rig.dep.prov_decision(
        rig.tok("researcher-1"), "d1").body["decision"]["world_seq"]


def test_hidden_decision_is_answered_as_unknown(rig):
    hidden = rig.dep.prov_decision(rig.tok("viewer-1"), "d1")
    absent = rig.dep.prov_decision(rig.tok("viewer-1"), "no-such-decision")
    assert (hidden.status, hidden.body) == (absent.status, absent.body) == ("INVALID", {"reason": "unknown_decision"})
    assert rig.dep.prov_object(rig.tok("viewer-1"), "Evidence:EV-C1").body == {"reason": "not_found"}
    assert rig.dep.prov_object(rig.tok("researcher-2"), "Evidence:EV-C1").body["decisions"] == ["d1"]


def test_authority_used_as_is_own_only_and_always_partial(rig):
    own = rig.dep.authority_used_as(rig.tok("researcher-1"), "d1")
    check_low_result("authority_used_as", own)
    assert own.body["path"] == [] and own.body["authority_version"] == {"redacted": "digest"}
    other, absent = rig.dep.authority_used_as(rig.tok("researcher-2"), "d1"), rig.dep.authority_used_as(rig.tok("researcher-2"), "nope")
    assert (other.status, other.body) == (absent.status, absent.body) == ("INVALID", {"reason": "unknown_decision"})


@pytest.mark.parametrize("mut,expect", [("provenance_edge_retained", "researcher-1"), ("redaction_fabrication", "system")])
def test_provenance_mutants(tmp_path, anchor, mut, expect):
    r = G3Rig(tmp_path, v3=True, mutants=[mut], history=HistoryStore(str(tmp_path / "h.sqlite")), anchor=anchor.client())
    r.dep.direct(r.tok("researcher-1"), *ATT, request_id="d1")
    d = r.dep.prov_decision(r.tok("researcher-2"), "d1").body["decision"]
    assert d["subject"] == expect and not is_marker(d["subject"])            # the clean build returns the marker (test above)
