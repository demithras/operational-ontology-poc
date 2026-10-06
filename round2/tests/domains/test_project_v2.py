"""Project Ontology v1 vs v2 contract: the attach_evidence -> evidence_count gap and its v2 fix (CHANGES_v2.md)."""
from __future__ import annotations

from prj_helpers import EVIDENCE_002, Snap, drop_link, failed_gates, make, next_engine, prop, seed

R1 = "researcher-1"


def _attach(e, ids, tag="a"):
    for i, ev in enumerate(ids):
        assert e.propose("attach_evidence", {"hypothesis": "H15", "evidence": ev}, R1,
                         idempotency_key=f"{tag}{i}")["state"] == "RECONCILED_SUCCESS"


def _verdict_row(git):
    return next(c["row"] for c in git.commits if c["target"] == "Verdict")


def _draft_no_supports(s):
    _drop_all_supports(s)
    prop(s, "Hypothesis", "H15", phase="DRAFT", freeze_hash=None)


def _drop_all_supports(s):
    for o in [o for o in s["ops"] if o["op"] == "create" and o["type"] == "Evidence"]:
        drop_link(s, "SUPPORTS_OR_REFUTES", o["key"])

def test_FINDING_attach_evidence_does_not_create_the_link_evidence_count_reads():
    """IR gap in v1 (the frozen Gate-0 IR), fixed in v2 (see domains/project/CHANGES_v2.md): ``evidence_count`` reads
    SUPPORTS_OR_REFUTES but v1 ``attach_evidence`` only creates PRODUCES. With no pre-declared SUPPORTS_OR_REFUTES link
    a derivable SUPPORTED verdict is refused (count 0). Pinned to the v1 IR."""
    e, git, _, sd = make("RUNNING", mutator=_drop_all_supports, ir_version="v1")
    _attach(e, EVIDENCE_002)
    e2 = next_engine(sd, git, ir_version="v1")
    assert e2.call_function("derive_verdict", {"hypothesis": "H15"}) == "SUPPORTED" and \
        e2.call_function("evidence_count", {"hypothesis": "H15"}) == 0
    z = Snap(e2, git)
    rec = e2.propose("evaluate_hypothesis", {"hypothesis": "H15"}, R1, idempotency_key="ev")
    assert rec["state"] == "DENIED" and failed_gates(rec) == ["preconditions"] and z.unchanged()


def test_v2_attach_evidence_creates_the_link_so_a_lifecycle_verdict_is_possible():
    """v2: create -> preregister -> start_run -> attach_evidence -> evaluate_hypothesis purely through Engine actions;
    the seed holds NO SUPPORTS_OR_REFUTES link for the evidence."""
    sd = seed("RUNNING", _draft_no_supports)
    assert not [o for o in sd["ops"] if o["op"] == "link" and o["type"] == "SUPPORTS_OR_REFUTES"]
    e, git, _, sd = make(sd=sd)
    assert e.propose("create_hypothesis", {"claim": "a fresh claim"}, R1, idempotency_key="c")["state"] == "RECONCILED_SUCCESS"
    fh = e.call_function("compute_freeze_hash", {"experiment": "exp-h15-002"})
    assert e.propose("preregister_hypothesis", {"hypothesis": "H15", "freeze_hash": fh}, R1,
                     idempotency_key="p")["state"] == "RECONCILED_SUCCESS"
    e = next_engine(sd, git)
    assert e.propose("start_run", {"hypothesis": "H15"}, R1, idempotency_key="r")["state"] == "RECONCILED_SUCCESS"
    e = next_engine(sd, git)
    assert e.get("Hypothesis", "H15")["props"]["phase"] == "RUNNING"
    assert e.call_function("evidence_count", {"hypothesis": "H15"}) == 0
    _attach(e, EVIDENCE_002)
    e2 = next_engine(sd, git)
    assert e2.call_function("evidence_count", {"hypothesis": "H15"}) >= 1
    assert e2.call_function("derive_verdict", {"hypothesis": "H15"}) == "SUPPORTED"
    rec = e2.propose("evaluate_hypothesis", {"hypothesis": "H15"}, R1, idempotency_key="ev")
    assert rec["state"] == "RECONCILED_SUCCESS" and _verdict_row(git)["value"] == "SUPPORTED"
    assert "machine-derived" in _verdict_row(git)["reason"]
    links = [c for c in git.commits if c["target"] == "SUPPORTS_OR_REFUTES"]
    assert len(links) == len(EVIDENCE_002) and all(c["row"]["$dst"] == "H15" for c in links)


def test_v2_negative_control_evaluate_without_attached_evidence_cannot_support_or_reject():
    e, git, _, _ = make("RUNNING", mutator=_drop_all_supports)
    assert e.call_function("evidence_count", {"hypothesis": "H15"}) == 0
    assert e.call_function("derive_verdict", {"hypothesis": "H15"}) == "INCONCLUSIVE"
    rec = e.propose("evaluate_hypothesis", {"hypothesis": "H15"}, R1, idempotency_key="ev")
    verdicts = [c["row"]["value"] for c in git.commits if c["target"] == "Verdict"]
    assert not set(verdicts) & {"SUPPORTED", "REJECTED"}
    assert rec["state"] == "DENIED" or verdicts == ["INCONCLUSIVE"]
