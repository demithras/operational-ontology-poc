"""The reference fake honours the P1d protocol (world_log marks, tx.tick, history+anchor integration, tamper detection)."""
import os
import shutil
import tempfile
import pytest
from r3_shared.anchor import start_anchor
from r3_shared.clock import LogicalClock
from r3_shared.histstore import HistoryStore, TamperView
from r3_shared.identity import IdentityProvider
from r3_shared.variant import Deployment
from r3_shared.world import WorldStore
from tests.fakes.fake_variant import FakeVariant

PART = ("Part", None)


def sc(ops=("put",)):
    return {"operations": list(ops), "resources": [{"type": "Part", "keys": None}]}


def edge(id_, issuer, child, parent=None, exp=None, redel=True, scope=None):
    return {"id": id_, "issuer": issuer, "child": child, "parent": parent, "scope": scope or sc(),
            "expires_at": exp, "redelegable": redel, "issued_at": 0}


@pytest.fixture
def env(tmp_path):
    clock, idp = LogicalClock(1), IdentityProvider("secret-secret")
    store = WorldStore(tmp_path / "w.db", clock=clock)
    hist = HistoryStore(str(tmp_path / "h.db"))
    sockdir = tempfile.mkdtemp(prefix="anc")
    ap = start_anchor(str(tmp_path / "anchor"), os.path.join(sockdir, "s"))
    dep = FakeVariant().deploy("manufacturing", store.handle_factory(), idp.verifier(), {}, {"a": 1}, clock, history=hist, anchor=ap.client())
    tok = lambda who: idp.issue(who, "fake", 1000, clock)
    yield type("E", (), dict(dep=dep, tok=tok, store=store, hist=hist, ap=ap, clock=clock, tmp=tmp_path, idp=idp))
    if ap.proc.poll() is None:
        ap.proc.kill()
    shutil.rmtree(sockdir, ignore_errors=True)


def test_fake_has_full_gate2_protocol(env):
    assert isinstance(env.dep, Deployment)


def test_delegate_revoke_rules_marks_and_durability(env):
    d, t = env.dep, env.tok
    assert d.delegate(t("alice"), edge("e1", "alice", "bob"), "r1").body == {"edge_id": "e1"}
    assert d.delegate(t("alice"), edge("e1", "alice", "carol"), "r2").body["reason"] == "duplicate_edge"
    assert d.delegate(t("bob"), edge("e2", "bob", "bob", "e1"), "r3").body["reason"] == "delegation_cycle"
    assert d.delegate(t("bob"), edge("e2", "bob", "alice", "e1"), "r4").body["reason"] == "delegation_cycle"
    assert d.delegate(t("bob"), edge("e2", "bob", "carol", "e1", scope=sc(["put", "zap"])), "r5").body["reason"] == "scope_amplification"
    assert d.delegate(t("bob"), edge("e2", "bob", "carol", "zz"), "r6").body["reason"] == "unknown_parent"
    assert d.delegate(t("alice"), edge("e2", "alice", "carol", "e1"), "r7").body["reason"] == "not_parent_holder"
    assert d.delegate(t("alice"), edge("e9", "alice", "carol", exp=1), "r8").body["reason"] == "already_expired"
    assert d.delegate(t("bob"), edge("e2", "bob", "carol", "e1", exp=9), "r9").status == "OK"
    assert d.revoke(t("carol"), "e1", "r10").body["reason"] == "not_revoker"
    assert d.revoke(t("alice"), "e1", "r11").status == "OK"          # upstream issuer cuts downstream
    assert d.revoke(t("alice"), "e1", "r12").body == {"already": True}
    assert d.delegate(t("bob"), edge("e3", "bob", "dave", "e1"), "r13").body["reason"] == "parent_invalid"
    log = env.store.reader().log()
    auth = [x for x in log if x["kind"] == "mark" and x["ref"] == "authority"]
    assert [a["data"]["op"] for a in auth] == ["delegate", "delegate", "revoke", "revoke"]  # refusals wrote nothing
    assert all(x["tag"] == "authority" and x["tick"] == 1 for x in auth)
    d.crash()
    d.restart()
    assert d.revoke(t("alice"), "e2", "r14").status == "OK" and d.g2["edges"][0]["id"] == "e1"  # edges survived restart
    assert d.delegate(t("alice"), edge("e1", "alice", "bob"), "r1").body == {"edge_id": "e1"}   # idempotent request_id


def test_authority_used_and_unknown_request(env):
    d, t = env.dep, env.tok
    assert d.authority_used("nope").body == {"reason": "unknown_request"} and d.authority_used("nope").status == "INVALID"
    env.clock.advance(4)
    assert d.direct(t("alice"), "put", {"type": "Part", "key": "P1"}, "root", "q1").status == "OK"
    u = d.authority_used("q1").body
    commit = [x for x in env.store.reader().log() if x["ref"] == "commit"][-1]
    assert u["world_seq"] == commit["seq"] and u["tick"] == 5 and u["on_behalf_of"] == "root" and u["path"] == []


def test_replay_verified_then_tamper_detected_via_anchor(env):
    d, t = env.dep, env.tok
    for i in range(3):
        assert d.direct(t("alice"), "put", {"type": "Part", "key": f"P{i}"}, request_id=f"q{i}").status == "OK"
    for i in range(3):
        r = d.replay(f"q{i}")
        assert r.status == "VERIFIED" and r.envelope["seq"] == i + 1 and d.explain(f"q{i}") == r
    assert d.replay("zzz").status == "UNRESOLVED"
    tv = TamperView(str(env.tmp / "h.db"))
    k = tv.keys("env/")[0]
    tv.write(k, tv.read(k).replace(b"alice", b"mallo"))
    assert [d.replay(f"q{i}").status for i in range(3)] == ["TAMPERED"] * 3  # chain back to seq 1 no longer matches the anchor
    tv.write(k, tv.read(k).replace(b"mallo", b"alice"))
    assert [d.replay(f"q{i}").status for i in range(3)] == ["VERIFIED"] * 3  # restoring the bytes restores the verdict
    art = tv.keys("art/")[0]
    saved = tv.read(art)
    tv.delete(art)
    assert d.replay("q1").status == "UNRESOLVED" and d.replay("q1").reason == "missing_artifact"
    tv.write(art, b"{}")
    assert d.replay("q1").status == "TAMPERED"
    tv.write(art, saved)
    info = env.ap.close()
    assert info["head"]["entries"] == 3 and [x["op"] for x in tv.log()] == ["write", "write", "delete", "write", "write"]


def test_no_anchor_is_unresolved(tmp_path):
    clock, idp = LogicalClock(), IdentityProvider("secret-secret")
    st = WorldStore(tmp_path / "w.db", clock=clock)
    dep = FakeVariant().deploy("manufacturing", st.handle_factory(), idp.verifier(), {}, {}, clock)
    r = dep.replay("x")
    assert (r.status, r.reason, r.envelope, r.artifacts) == ("UNRESOLVED", "no_anchor", None, {})
