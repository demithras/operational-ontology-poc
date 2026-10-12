"""H29 oracle units: lease rule, classifier, blocked-reply admissibility, recovery model forms, isolation scan (C29-0) + known negative."""
import shutil

from r3_harness.h29 import evalchecks as EC
from r3_oracle import continuity as C
from r3_oracle import recoverymodel as RM


def V(seq, req, eff, digest="d"):
    return {"seq": seq, "digest": digest, "requested_tick": req, "effective_tick": eff}


def test_grant_until_and_strict_upper_bound():
    vs = [V(1, 0, 0, "a")]
    assert C.grant_until(vs, 3) == 7
    assert C.lease_valid(3, 7, 6) and not C.lease_valid(3, 7, 7)          # strict: valid for t < lease_until
    vs2 = vs + [V(2, 3, 7, "b")]                                          # a publish at 3 pends until 7
    assert C.grant_until(vs2, 4) == 7 and C.grant_until(vs2, 7) == 11
    assert C.authority_in_force(vs2, 6) == "a" and C.authority_in_force(vs2, 7) == "b"


def _graph():
    from r3_harness.h29 import specs
    return specs.graph()


def test_classify_lease_window_blocked_and_unresolved():
    g, vs = _graph(), [V(1, 0, 0, "a")]
    phi = C.Phi([{"node": "AUTH", "mode": "drop", "from_tick": 4, "to_tick": 12}], [])
    sends = [{"kind": "request", "op": "transfer_inventory", "t": 3, "invalid_probe": False}]
    renew = C.lease_sends(sends, phi, g, "manufacturing")
    q = lambda t: {"kind": "request", "op": "transfer_inventory", "t": t, "rid": "r"}   # noqa: E731
    assert C.classify(q(6), phi, g, "manufacturing", renew, vs).kind == C.SAFE          # lease from 3 valid until 7
    assert C.classify(q(7), phi, g, "manufacturing", renew, vs).kind == C.BLOCKED
    assert C.classify(q(7), phi, g, "manufacturing", renew, vs).down == ["AUTH"]
    phi2 = C.Phi([{"node": "ANCHOR", "mode": "reply_lost", "from_tick": 4, "to_tick": 9}], [])
    assert C.classify(q(5), phi2, g, "manufacturing", [], vs).kind == C.UNRESOLVED
    assert C.classify(q(5), phi2, g, "manufacturing", [], vs, crashed_rids={"r"}).kind == C.UNRESOLVED
    ro = C.Phi([], [(3, 6)])                                                            # lease use across an ENGINE restart: permitted, not required
    c = C.classify(q(5), C.Phi([{"node": "AUTH", "mode": "drop", "from_tick": 4, "to_tick": 12}], [(4, 5)]), g, "manufacturing", renew, vs)
    assert c.kind == C.SAFE and not c.strict
    assert ro.engine_down(4) and not ro.engine_down(6)


def test_blocked_reply_vocabulary():
    cls = C.Cls(C.BLOCKED, ["AUTH"])
    ok = lambda s, b, inv=False: C.blocked_reply_ok(cls, s, b, inv)[0]   # noqa: E731
    assert ok("UNAVAILABLE", {"reason": "dependency_unavailable", "dependency": "AUTH"})
    assert not ok("UNAVAILABLE", {"reason": "dependency_unavailable", "dependency": "ANCHOR"})     # names a node that is not down
    assert not ok("DENIED", {"reason": "not_authorized"}) and not ok("OK", {})
    assert not ok("INVALID", {"reason": "schema_invalid"}, inv=False) and ok("INVALID", {"reason": "schema_invalid"}, inv=True)
    assert not ok("INVALID", {"reason": "weird"}, inv=True)
    assert ok("UNKNOWN", {"reason": "in_doubt"}) and not ok("UNKNOWN", {"reason": "x"})


def test_recovery_model_forms():
    a = {"form": "r3-recovery-1", "committed": [], "intents": [], "authority": {"version": None, "lease_until": None}, "approvals_open": []}
    b = {**a, "authority": {"version": "x", "lease_until": 5}}
    assert RM.view_diff(a, a) == [] and RM.view_diff(a, b) == ["authority.lease_until", "authority.version"]
    p = RM.predict_view([], {}, [V(1, 0, 0, "a")], 3, ["f" * 64, "f" * 64])
    assert p["authority"] == {"version": "a", "lease_until": 7} and p["approvals_open"] == ["f" * 64]


def test_replayer_approval_fingerprint_g5_e11():
    from r3_harness.h29 import specs
    from r3_oracle.recoverymodel import Replayer
    from r3_shared.extadapter import canon_json
    import hashlib
    ops, auth, _ = specs.load("manufacturing")
    rep = Replayer(ops, specs.seed_snapshot(ops))
    args = {"po_id": "PO-992", "expedite_fee": 900}
    ok = rep.approve(auth, "supervisor-1", "planner-1", None, "expedite_purchase_order", args)
    if ok:
        want = hashlib.sha256(canon_json({"subject": "planner-1", "on_behalf_of": None, "operation": "expedite_purchase_order", "inputs": args}).encode()).hexdigest()
        assert rep.open_approvals() == [want]


def test_oracle_isolation_scan_and_known_negative(tmp_path):
    ok, bad = EC.oracle_isolation()
    assert ok, bad
    d = tmp_path / "r3_oracle"
    shutil.copytree(EC.ROUND3 / "src" / "r3_oracle", d)
    (d / "continuity.py").write_text((d / "continuity.py").read_text() + "\nimport paladin.core\n")      # FakeOracleImporter
    ok2, bad2 = EC.oracle_isolation(d)
    assert not ok2 and any("paladin" in b for b in bad2)
    (d / "continuity.py").write_text((EC.ROUND3 / "src/r3_oracle/continuity.py").read_text() + "\nX = 'world_log'\n")
    assert not EC.oracle_isolation(d)[0]              # world_log is allowed in recoverymodel only


def test_world_digest_compares_loose_verdict_props_by_form_only():
    """Verdict reason / derivation_hash are specified loosely (ops_model.LOOSE_PROPS): two well-formed texts digest equal, a blank reason or a
    non-hex hash is a divergence (known-negative)."""
    from r3_oracle import recoverymodel as RM

    def snap(reason, h):
        return {"objects": {"Verdict:v1": {"props": {"id": "v1", "reason": reason, "derivation_hash": h, "value": "SUPPORTED"}, "version": 1}}, "links": []}
    a, b = "a" * 64, "b" * 64
    assert RM.world_digest(snap("machine-derived x", a)) == RM.world_digest(snap("experiment=E; evidence=1", b))
    assert RM.world_digest(snap("  ", a)) != RM.world_digest(snap("experiment=E", a))
    assert RM.world_digest(snap("ok", "zz")) != RM.world_digest(snap("ok", a))
    other = snap("ok", a)
    other["objects"]["Verdict:v1"]["props"]["value"] = "REJECTED"
    assert RM.world_digest(other) != RM.world_digest(snap("ok", a))
