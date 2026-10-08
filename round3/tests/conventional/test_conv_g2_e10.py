"""E-10: replay re-derives the authority verdict only for OK/DENIED decisions (INVALID is verified structurally)."""
import json

from conv_g2_util import make_g2, sha, tamper

BAD = {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": "PX-17", "quantity": 1}
NOPE = {**BAD, "quantity": -1}  # existing targets, failing ONLY a precondition (G3-E17: a deny rule would answer DENIED)


def _invalid(r, who, rid, body=None):
    res = r.dep.direct(r.token(who), "transfer_inventory", body or NOPE, None, rid)
    assert res.status == "INVALID", (res.status, res.body)
    return res


def test_e10_clean_invalid_decision_replays_verified_even_for_an_unauthorised_caller(tmp_path):
    r = make_g2(tmp_path, with_history=True)
    try:
        # this build checks authority first: an unauthorised caller is DENIED, so INVALID is reached by authorised callers
        _invalid(r, "planner-1", "i1")  # precondition failure
        _invalid(r, "planner-1", "i2", {**BAD, "quantity": 0})
        f = r.redeploy()
        assert f.replay("i1").status == "VERIFIED" and f.replay("i2").status == "VERIFIED"
    finally:
        r.close()


def test_e10_tampered_invalid_decision_is_still_detected(tmp_path):
    r = make_g2(tmp_path, with_history=True)
    try:
        _invalid(r, "planner-1", "i1")
        stream = r.history.get("meta/stream").decode()
        seq = r.anchor.lookup(stream, "i1")["seq"]
        key = f"env/{seq:010d}"
        env = json.loads(r.history.get(key))
        env["decision"]["reason"] = "forged"
        from r3_shared.evidence import canonical_bytes
        t = tamper(r)
        t.write(key, canonical_bytes(env))
        res = r.redeploy().replay("i1")
        assert res.status in ("TAMPERED", "UNRESOLVED"), res
    finally:
        r.close()
