"""P1h operator plane (PROT-H30 s2.1): identity revocation honoured by BOTH TokenVerifier paths, ExternalWorld cap revocation and
route quarantine enforced SERVER SIDE with audit rows, one recorded operator action per call, and byte-identity when unused."""
import hashlib
import json
import sqlite3

import pytest
from r3_shared import extcap
from r3_shared.clock import LogicalClock
from r3_shared.extadapter import payload_digest
from r3_shared.extsystems import load_systems
from r3_shared.extworld import ExternalClient, ExternalError, _call, start_external
from r3_shared.extworld_core import REFUSALS, REFUSALS_G6, ExternalWorldCore
from r3_shared.identity import REVOCATION_ENV, IdentityProvider, RevocationList, TokenError, TokenVerifier
from r3_shared.opplane import ACTIONS, OPERATOR_AUD, REFUSAL_REASONS, SERVER_REASONS, OperatorError, OperatorPlane
from tests.p1f_util import KEY, PAY, TARGET, audit, cap_for, core, eff_count

AUD = "svc"


def _env(tmp_path):
    clock = LogicalClock(5)
    rev = RevocationList(tmp_path / "rev.jsonl")
    idp = IdentityProvider("user-secret-1", rev)
    plane = OperatorPlane("operator-secret-1", clock, idp, None, tmp_path / "ops.jsonl")
    return clock, idp, plane


def W(c, cap):
    return c.write(cap, "expedite", TARGET, PAY, "adp")


# ---- identity -----------------------------------------------------------------------------------------------------------
def test_revoked_subject_is_refused_by_both_verifier_paths_and_others_are_not(tmp_path):
    clock, idp, plane = _env(tmp_path)
    ta, tb = idp.issue("alice", AUD, 100, clock), idp.issue("bob", AUD, 100, clock)
    v = idp.verifier()
    assert v.verify(ta, AUD, clock) == "alice" and v.claims(ta, AUD, clock)["sub"] == "alice"       # honest reference stays clean
    plane.revoke_subject(plane.operator_token(), "alice")
    for call in (lambda: v.verify(ta, AUD, clock), lambda: v.claims(ta, AUD, clock)):
        with pytest.raises(TokenError, match="revoked"):
            call()
    assert v.verify(tb, AUD, clock) == "bob"
    with pytest.raises(TokenError, match="revoked"):                                              # a token issued AFTER the revocation too
        v.verify(idp.issue("alice", AUD, 100, clock), AUD, clock)
    assert [r["reason"] for r in idp.revocations.rows()] == ["revoked_subject"]


def test_revoked_token_refuses_only_that_token(tmp_path):
    clock, idp, plane = _env(tmp_path)
    t1, t2 = idp.issue("alice", AUD, 100, clock), idp.issue("alice", AUD, 100, clock)
    v = idp.verifier()
    plane.revoke_token(plane.operator_token(), t1)
    with pytest.raises(TokenError, match="revoked"):
        v.verify(t1, AUD, clock)
    with pytest.raises(TokenError, match="revoked"):
        v.claims(t1, AUD, clock)
    assert v.verify(t2, AUD, clock) == "alice"
    assert t1 not in json.dumps(plane.actions())                                                  # the bearer token is never logged


def test_revocation_is_effective_for_the_next_verification_even_for_a_verifier_built_earlier(tmp_path):
    clock, idp, plane = _env(tmp_path)
    t = idp.issue("alice", AUD, 100, clock)
    v = TokenVerifier(idp._secret, RevocationList(idp.revocations.path))                         # a separate reader of the same file (host process)
    assert v.verify(t, AUD, clock) == "alice"
    plane.revoke_subject(plane.operator_token(), "alice")
    with pytest.raises(TokenError, match="revoked"):
        v.verify(t, AUD, clock)


def test_env_variable_wires_a_verifier_built_without_a_list(tmp_path, monkeypatch):
    clock, idp, plane = _env(tmp_path)
    t = idp.issue("alice", AUD, 100, clock)
    plane.revoke_subject(plane.operator_token(), "alice")
    bare = IdentityProvider("user-secret-1")                                   # how host._build constructs it: no list argument
    assert bare.verifier().verify(t, AUD, clock) == "alice"                    # env unset: no revocation consulted (byte-identical path)
    monkeypatch.setenv(REVOCATION_ENV, str(idp.revocations.path))
    with pytest.raises(TokenError, match="revoked"):
        bare.verifier().verify(t, AUD, clock)


def test_forged_and_expired_tokens_keep_their_own_errors_before_revocation(tmp_path):
    clock, idp, plane = _env(tmp_path)
    v = idp.verifier()
    t = idp.issue("alice", AUD, 1, clock)
    clock.advance(3)
    with pytest.raises(TokenError, match="expired"):
        v.verify(t, AUD, clock)
    with pytest.raises(TokenError, match="bad signature"):
        v.verify(t[:-2] + ("aa" if not t.endswith("aa") else "bb"), AUD, clock)


# ---- operator authentication and accounting -----------------------------------------------------------------------------
def test_operator_calls_need_an_operator_token_and_failures_are_recorded_but_not_counted(tmp_path):
    clock, idp, plane = _env(tmp_path)
    user = idp.issue("alice", OPERATOR_AUD, 100, clock)                      # right audience, wrong issuer secret
    other_aud = IdentityProvider("operator-secret-1").issue("operator", "svc", 100, clock)
    for bad in (user, other_aud, "junk"):
        with pytest.raises(OperatorError) as e:
            plane.revoke_subject(bad, "bob")
        assert e.value.reason == "operator_auth_failed"
    assert idp.revocations.rows() == []                                      # nothing was revoked
    assert plane.count_actions() == 0 and [r["outcome"] for r in plane.actions()] == ["refused"] * 3
    plane.revoke_subject(plane.operator_token(), "bob")
    assert plane.count_actions() == 1
    with pytest.raises(OperatorError) as e:
        plane.revoke_subject(plane.operator_token(), "")
    assert e.value.reason == "invalid_arguments" and plane.count_actions() == 1
    assert {r["reason"] for r in plane.actions() if r["outcome"] == "refused"} <= set(REFUSAL_REASONS)
    on_disk = [json.loads(line) for line in (tmp_path / "ops.jsonl").read_text().splitlines()]
    assert on_disk == plane.actions() and {r["action"] for r in on_disk} <= set(ACTIONS)


def test_frozen_reason_vocabularies():
    assert REFUSALS_G6 == ("revoked_chain", "route_quarantined") == SERVER_REASONS["external"]
    assert SERVER_REASONS["identity"] == ("revoked_subject", "revoked_token")
    assert len(REFUSALS) == 9                                                # the P1f-2 vocabulary is untouched
    schema = json.loads(open("schemas/external-ledger.schema.json").read())
    assert set(REFUSALS_G6) <= set(schema["$defs"]["audit_row"]["properties"]["reason"]["enum"])


# ---- ExternalWorld, in-process core -------------------------------------------------------------------------------------
def test_chain_revocation_is_enforced_before_the_effect_and_audited():
    c = core()
    c.advance(2)
    cap = cap_for(c, correlation="r1#0", max_uses=2)
    other = cap_for(c, correlation="r2#0", max_uses=2)
    assert W(c, cap)["status"] == "applied"
    seq = c.revoke_chain(chain_id=extcap.chain_id(cap))
    n = eff_count(c)
    r = W(c, cap)
    assert (r["status"], r["reason"]) == ("refused", "revoked_chain") and eff_count(c) == n          # no effect
    last = audit(c)[-1]
    assert (last["outcome"], last["reason"], last["cap_chain"], last["deployment"]) == ("refused", "revoked_chain", extcap.chain_id(cap), "dep1")
    assert W(c, other)["status"] == "applied"                                                         # another chain of the same root is unharmed
    assert c.op_log() == [{"seq": seq, "tick": 2, "action": "revoke_chain", "args": {"chain_id": extcap.chain_id(cap)}, "operator": "operator"}]


def test_root_revocation_covers_every_chain_of_that_root():
    c = core()
    root = c.issue_root("dep1", "ERP")
    nonce = extcap.root_nonce(root)
    mk = lambda cor: extcap.attenuate(root, system="ERP", operation="expedite", target=TARGET, payload_digest=payload_digest(PAY),  # noqa: E731
                                      correlation=cor, max_uses=1, not_after_tick=9)
    assert W(c, mk("a#0"))["status"] == "applied"
    c.revoke_chain(root_nonce=nonce)
    assert [W(c, mk(x))["reason"] for x in ("b#0", "c#0")] == ["revoked_chain"] * 2
    other_dep = cap_for(c, dep="dep2", correlation="z#0")                                          # a different root: unaffected
    assert W(c, other_dep)["status"] == "applied"


def test_quarantine_blocks_only_the_named_route():
    c = core()
    c.quarantine("ERP", "dep1")
    n = eff_count(c)
    r = W(c, cap_for(c, dep="dep1"))
    assert (r["status"], r["reason"]) == ("refused", "route_quarantined") and eff_count(c) == n
    assert audit(c)[-1]["reason"] == "route_quarantined"
    assert W(c, cap_for(c, dep="dep2", correlation="o#0"))["status"] == "applied"                  # same system, other deployment
    c.advance(0)
    wms = cap_for(c, system="WMS", operation="transfer", target="transfer:P@A->B", payload={"x": 1}, dep="dep1", correlation="w#0")
    r = c.write(wms, "transfer", "transfer:P@A->B", {"x": 1}, "adp")                                # same deployment, other system: not quarantined
    assert r["reason"] != "route_quarantined"


def test_unauthenticated_caps_are_not_attributed_by_the_new_checks():
    c = core()
    cap = cap_for(c)
    c.quarantine("ERP", "dep1")
    forged = cap[:-3] + ("AAA" if not cap.endswith("AAA") else "BBB")
    assert W(c, forged)["reason"] == "bad_signature"                       # signature first: a forged cap is never attributed to a quarantined route
    assert audit(c)[-1]["deployment"] == ""


def test_operator_arguments_are_validated():
    c = core()
    with pytest.raises(ValueError):
        c.revoke_chain()
    with pytest.raises(ValueError):
        c.revoke_chain(root_nonce="a", chain_id="b" * 64)
    with pytest.raises(ValueError):
        c.revoke_chain(root_nonce="not-issued")
    with pytest.raises(ValueError):
        c.revoke_chain(chain_id="xyz")
    with pytest.raises(ValueError):
        c.quarantine("NOPE", "dep1")


def _tables(c):
    return sorted(r[0] for r in c.con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))


def test_unused_plane_leaves_the_ledger_bit_identical_in_shape():
    used, unused = core(), core()
    assert _tables(unused) == ["audit", "effects", "issued", "meta", "obs_keys", "sysstate"]        # the G5 DDL: no op_log, no new table
    W(unused, cap_for(unused))
    unused_rows = (audit(unused), unused.con.execute("SELECT * FROM effects").fetchall())
    used.quarantine("WMS", "never-used")                                                              # touches only a route nothing uses
    W(used, cap_for(used))
    assert (audit(used), used.con.execute("SELECT * FROM effects").fetchall()) == unused_rows        # an unrelated action changes no row
    assert "op_log" in _tables(used)


# ---- ExternalWorld, real service process through the plane --------------------------------------------------------------
def test_plane_drives_a_real_externalworld_process(tmp_path):
    systems = tmp_path / "systems.json"
    systems.write_text(json.dumps(load_systems("manufacturing")))
    sock = str(tmp_path / "e.sock")
    proc = start_external(tmp_path / "ext", systems, sock)
    try:
        cli = ExternalClient(sock, sock + ".ctl")
        clock = LogicalClock(3)
        plane = OperatorPlane("operator-secret-1", clock, None, cli)
        tok = plane.operator_token()
        root = cli.issue_root("dep1", "ERP")
        cap = extcap.attenuate(root, system="ERP", operation="expedite", target=TARGET, payload_digest=payload_digest(PAY),
                               correlation="r1#0", max_uses=3, not_after_tick=99)
        assert cli.write(cap, "expedite", TARGET, PAY, "adp").status == "applied"
        plane.revoke_chain(tok, chain_id=extcap.chain_id(cap))
        r = cli.write(cap, "expedite", TARGET, PAY, "adp")
        assert (r.status, r.reason) == ("refused", "revoked_chain")
        for op in ("revoke_chain", "quarantine", "op_log"):                                            # the DATA plane cannot reach operator ops
            with pytest.raises(ExternalError, match="not available on the data plane"):
                _call(sock, {"op": op, "chain_id": "0" * 64, "system": "ERP", "deployment": "dep1"})
        plane.quarantine_route(tok, "ERP", "dep1")
        cap2 = extcap.attenuate(root, system="ERP", operation="expedite", target=TARGET, payload_digest=payload_digest(PAY),
                                correlation="r2#0", max_uses=1, not_after_tick=99)
        assert cli.write(cap2, "expedite", TARGET, PAY, "adp").reason == "route_quarantined"
        assert [(r["action"], r["outcome"]) for r in plane.actions()] == [("revoke_chain", "done"), ("quarantine_route", "done")]
        assert [r["action"] for r in cli.op_log()] == ["revoke_chain", "quarantine"]
        with pytest.raises(OperatorError) as e:
            plane.revoke_chain(tok, root_nonce="no-such-root")
        assert e.value.reason == "invalid_arguments"
    finally:
        out = proc.close()
    con = sqlite3.connect(f"file:{tmp_path / 'ext' / 'external.db'}?mode=ro", uri=True)
    reasons = [r[0] for r in con.execute("SELECT reason FROM audit ORDER BY seq")]
    assert reasons == ["", "revoked_chain", "route_quarantined"] and out["head"]["effects"] == 1
