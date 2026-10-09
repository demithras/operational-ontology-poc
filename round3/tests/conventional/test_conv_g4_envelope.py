"""Q13 / P1f-7: with HistoryStore + anchor, ExternalRequest.envelope_text is the byte-exact H27 envelope of the decision."""
import json

from conv_g4_util import EXPEDITE, make_g4


def test_envelope_text_is_the_anchored_envelope_of_the_decision(tmp_path):
    r = make_g4(tmp_path, history=True)
    assert r.dep.call_tool(r.token("planner-1"), "expedite_purchase_order", EXPEDITE, request_id="e1").status == "OK"
    req = r.sent("ERP")[0]
    env = json.loads(req.envelope_text)
    assert env["decision"]["decision_id"] == "e1" and env["decision"]["status"] == "OK"
    seq = r.dep.service.anchor.lookup(r.dep.service.stream, "e1")["seq"]
    assert req.envelope_text.encode() == r.hist.get(f"env/{seq:010d}")          # byte-exact
    assert r.dep.replay("e1").status == "VERIFIED"


def test_no_history_means_empty_envelope_text(tmp_path):
    r = make_g4(tmp_path)
    r.dep.call_tool(r.token("planner-1"), "expedite_purchase_order", EXPEDITE, request_id="e2")
    assert r.sent("ERP")[0].envelope_text == ""
