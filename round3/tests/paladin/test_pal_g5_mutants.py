"""PROT-H29 s10 / P1g-10: each KNOWN["H29"] mutant at its real site, killed by its OWN class, with the clean build at 0 on the same subset
(kill rule G3/G4). The classes are the ones PROT-H29 names (computed here from the services' logs and the world store, never from the
variant's say-so): stale_authority_commit, forbidden_effect, progress < 0.95, stale_authority_after_restart, recovery_nondeterministic,
recovery_divergence, misclassified_dependency_failure, unanchored_ack."""
import hashlib
import shutil

import pytest

from g5_rig import DEP, EXP, RES, TR, G5Rig, narrowed
from paladin.variant import PaladinVariant
from r3_shared.authsvc import in_force
from r3_shared.histstore import HistoryStore
from r3_shared.mutants import KNOWN
from r3_shared.recovery import canon_json, validate_recovery_view
from r3_shared.world import WorldStore

H29 = KNOWN["H29"]
INPUT_INVALID = ("schema_invalid", "unknown_operation", "unknown_tool", "bad_args")


def marks(r):
    return {x["data"]["request_id"]: (x["data"]["authority_version"], x["tick"]) for x in r.reader.log(0) if x["kind"] == "mark" and x["ref"] == "commit"}


def misclassified(res):
    """R29-7 for a request whose oracle class is BLOCKED_BY_DEPENDENCY on AUTH."""
    if res.status in ("OK", "DENIED", "UNKNOWN"):
        return True
    if res.status == "INVALID":
        return res.body.get("reason") not in INPUT_INVALID
    return res.body.get("dependency") != "AUTH"


def run_stale_authority(mutants):
    r = G5Rig(mutants=mutants)
    try:
        r.call("planner-1", "transfer_inventory", TR, "m0")
        r.actl.publish(narrowed(r.auth0))                                       # effective at 4 (lease granted at 0 runs to 4)
        r.actl.outage(DEP, 1, 20, "drop")
        r.tick(5)                                                               # (the ops spec's own policy refuses transfers from tick 6 on)
        res = r.call("planner-1", "transfer_inventory", {**TR, "quantity": 2}, "m1")
        vs, got = r.actl.log()["versions"], marks(r)
        stale = [rid for rid, (v, t) in got.items() if t >= 4 and v != in_force(vs, t)]
        return {"stale_authority_commit": len(stale), "forbidden_effect": int(res.status == "OK"), "status": res.status}
    finally:
        r.finish()


def test_mutant_fail_open_on_authority_outage_killed_by_stale_authority_commit():
    clean, mut = run_stale_authority(()), run_stale_authority(("fail_open_on_authority_outage",))
    assert (clean["stale_authority_commit"], clean["forbidden_effect"], clean["status"]) == (0, 0, "UNAVAILABLE")
    assert mut["stale_authority_commit"] == 1 and mut["forbidden_effect"] == 1


def run_progress(mutants):
    """Four SAFE requests while an unrelated dependency is down (eligible = 4): ERP down, ANCHOR down for a read, AUTH reachable."""
    r = G5Rig(mutants=mutants)
    try:
        tok = r.token("planner-1")
        r.tick()
        r.ctl.outage("ERP", DEP, 1, 9)
        r.nctl.partition(r.dep._c.prov.stream, 2, 4, "drop")
        ok = 0
        ok += r.call("planner-1", "expedite_purchase_order", EXP, "p1").status == "OK"    # decision plane SAFE (ERP only on the outcome plane)
        r.dep.dispatch_pending()                                                          # the breaker for EXT:ERP trips here
        ok += r.call("planner-1", "transfer_inventory", TR, "p2").status == "OK"          # unrelated to ERP
        ok += r.call("planner-1", "reschedule_work_order", RES, "p3").status == "OK"
        r.tick()                                                                          # t=2: ANCHOR down, a read needs only AUTH
        ok += r.dep.read(tok, "list", {"type": "Part"}).status == "OK"
        return ok / 4
    finally:
        r.finish()


def test_mutant_global_halt_on_fault_killed_by_safe_progress_below_095():
    assert run_progress(()) == 1.0
    assert run_progress(("global_halt_on_fault",)) < 0.95


def run_stale_restart(mutants):
    r = G5Rig(mutants=mutants)
    try:
        r.call("planner-1", "transfer_inventory", TR, "s0")
        r.actl.publish(narrowed(r.auth0))
        r.actl.outage(DEP, 5, 30, "drop")
        r.tick(5)                                                                         # the old lease expired at 4, AUTH down, new version in force
        dep2 = r.deploy(resume=True)                                                      # a NEW deployment over the surviving stores
        a6 = in_force(r.actl.log()["versions"], 5)
        view = dep2.recovery_view()["authority"]["version"]
        res = r.call("planner-1", "transfer_inventory", {**TR, "quantity": 3}, "s1", dep=dep2)
        return {"stale_authority_after_restart": int(view is not None and view != a6), "stale_authority_commit": int(res.status == "OK"),
                "version": view}
    finally:
        r.finish()


def test_mutant_stale_cache_after_restart_killed_by_stale_authority_after_restart():
    clean, mut = run_stale_restart(()), run_stale_restart(("stale_cache_after_restart",))
    assert clean == {"stale_authority_after_restart": 0, "stale_authority_commit": 0, "version": None}
    assert mut["stale_authority_after_restart"] == 1 and mut["stale_authority_commit"] == 1


def salts_for(rid):
    """Two salts for which the mutant's unordered scan resolves the same in-doubt record differently."""
    win = lambda s: bool(hashlib.sha256(s + rid.encode()).digest()[0] & 1)   # noqa: E731
    a = next(bytes([i]) * 8 for i in range(256) if win(bytes([i]) * 8))
    b = next(bytes([i]) * 8 for i in range(256) if not win(bytes([i]) * 8))
    return a, b


def copy_deploy(r, name, mutants, salt, monkeypatch):
    d = r.root / name
    d.mkdir()
    for f in list(r.root.glob("world.db*")) + list(r.root.glob("hist.db*")):
        shutil.copy2(f, d / f.name)
    monkeypatch.setattr("paladin.core.os.urandom", lambda n: salt)
    return PaladinVariant(mutants).deploy(r.domain, WorldStore(d / "world.db", clock=r.clock).handle_factory(), r.idp.verifier(), r.ops, r.auth0,
                                          r.clock, history=HistoryStore(str(d / "hist.db")), anchor=r.anchor.client(),
                                          external=r.external_binding(), authority_source=r.binding(), resume=True)


def run_rc1(mutants, monkeypatch):
    r = G5Rig(mutants=mutants)
    try:
        r.dep.arm_crash("after_commit")
        assert r.call("planner-1", "transfer_inventory", TR, "n1").body == {"reason": "crashed"}   # committed, PREPARED row in doubt
        sa, sb = salts_for("n1")
        va = copy_deploy(r, "A", mutants, sa, monkeypatch).recovery_view()
        vb = copy_deploy(r, "B", mutants, sb, monkeypatch).recovery_view()
        expected = {"committed": ["n1"], "intents": [("n1", "PENDING")]}                    # the oracle set: the world holds the commit
        div = lambda v: int([c["request_id"] for c in v["committed"]] != expected["committed"]   # noqa: E731
                            or [(i["request_id"], i["state"]) for i in v["intents"]] != expected["intents"])
        return {"recovery_nondeterministic": int(canon_json(validate_recovery_view(va)) != canon_json(validate_recovery_view(vb))),
                "recovery_divergence": div(va) + div(vb)}
    finally:
        r.finish()


def test_mutant_nondeterministic_recovery_killed_by_recovery_nondeterministic(monkeypatch):
    assert run_rc1((), monkeypatch) == {"recovery_nondeterministic": 0, "recovery_divergence": 0}
    mut = run_rc1(("nondeterministic_recovery",), monkeypatch)
    assert mut["recovery_nondeterministic"] == 1 and mut["recovery_divergence"] >= 1


def run_denial(mutants):
    r = G5Rig(mutants=mutants)
    try:
        r.call("planner-1", "transfer_inventory", TR, "d0")
        r.actl.outage(DEP, 1, 30, "drop")
        r.tick(6)
        return sum(misclassified(r.call("planner-1", "transfer_inventory", {**TR, "quantity": q}, f"d{q}")) for q in (2, 3)), \
            {r.call("planner-1", "transfer_inventory", {**TR, "quantity": 5}, "d5").status}
    finally:
        r.finish()


def test_mutant_dependency_failure_as_denial_killed_by_misclassified_dependency_failure_with_zero_safety_impact():
    assert run_denial(()) == (0, {"UNAVAILABLE"})
    n, statuses = run_denial(("dependency_failure_as_denial",))
    assert n == 2 and statuses == {"DENIED"}                                              # wrong class only: still zero effects, no stale commit


def run_outbox(mutants):
    r = G5Rig(mutants=mutants)
    try:
        for s in r.systems["systems"]:
            r.ctl.outage(s, DEP, 0, 3)                                                      # inline dispatch (G5-E35 B2) finds the system down: intent stays due
        assert r.call("planner-1", "transfer_inventory", TR, "o1").status == "OK"          # intent durable, not dispatched
        r.tick(3)
        dep2 = r.deploy(resume=True)
        rc1 = [i["state"] for i in dep2.recovery_view()["intents"]]
        dep2.dispatch_pending()
        r.tick(12)
        out = dep2.reconcile("o1", r.clock.now() + 1).body["outcomes"]
        return {"rc1_admissible": int(set(rc1) <= {"PENDING", "UNKNOWN"}), "rc2": [o["state"] for o in out]}
    finally:
        r.finish()


def test_mutant_outbox_dropped_on_restart_killed_by_recovery_divergence():
    assert run_outbox(()) == {"rc1_admissible": 1, "rc2": ["RECONCILED_SUCCESS"]}
    mut = run_outbox(("outbox_dropped_on_restart",))
    assert mut == {"rc1_admissible": 0, "rc2": ["RECONCILED_FAILED"]}                       # RC1 AND RC2 diverge from the oracle


def run_anchor(mutants):
    r = G5Rig(mutants=mutants)
    try:
        stream = r.dep._c.prov.stream
        r.nctl.partition(stream, 1, 5, "drop")
        r.tick()
        res = r.call("planner-1", "transfer_inventory", TR, "u1")
        r.tick(5)
        anchored = r.anchor.client().lookup(stream, "u1") is not None
        return {"unanchored_ack": int(res.status == "OK" and not anchored), "committed": "u1" in marks(r), "status": res.status}
    finally:
        r.finish()


def test_mutant_anchor_skipped_when_unavailable_killed_by_unanchored_ack():
    assert run_anchor(()) == {"unanchored_ack": 0, "committed": False, "status": "UNAVAILABLE"}
    mut = run_anchor(("anchor_skipped_when_unavailable",))
    assert mut["unanchored_ack"] == 1 and mut["committed"] is True


def test_every_h29_mutant_has_a_kill_test_in_this_file():
    names = open(__file__).read()
    missing = [m for m in H29 if f"test_mutant_{m}_killed_by" not in names]
    assert missing == []                                                                    # set difference, not a count
