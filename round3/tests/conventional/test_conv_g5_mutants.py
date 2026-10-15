"""PROTOCOL-P1g P1g-10 / PROT-H29 s10: each H29 mutant sits at its REAL site and is killed by the test of its own class; the clean build
passes the very same scenario. Hand-written expectations (the clean build must be green, the mutant red)."""
from conv_g5_util import DEP, EXPEDITE, TRANSFER, V0, make_g5, narrowed, stop_all
from r3_shared.authsvc import doc_digest
from r3_shared.mutants import KNOWN
from r3_shared.recovery import canon_json


def run(tmp_path, mutants, fn, ext=False):
    r = make_g5(tmp_path / ("m" if mutants else "c"), mutants, ext=ext)
    try:
        return fn(r)
    finally:
        stop_all()


def stale_commit(r):
    """class stale_authority_commit / forbidden_effect: a decision past lease_until (F2 + F6 stale-sensitive request)."""
    r.d("planner-1", "transfer_inventory", {**TRANSFER, "quantity": 1}, "r0")       # lease [2, 6) of V0
    r.actl.publish(narrowed())                                                       # in force at tick 6
    r.actl.outage(DEP, 3, 20)
    r.tick(4)                                                                        # tick 6, AUTH down
    return r.d("planner-1", "transfer_inventory", {**TRANSFER, "quantity": 1}, "r1").status, r.commits()


def global_halt(r):
    """class progress (iii): ERP down trips its breaker; an UNRELATED operation (WMS transfer) must still progress."""
    r.ectl.outage("ERP", DEP, 2, 30)
    r.d("planner-1", "expedite_purchase_order", EXPEDITE, "e1")
    r.dep.dispatch_pending()
    return r.d("planner-1", "transfer_inventory", TRANSFER, "t1").status


def stale_restart(r):
    """class stale_authority_after_restart: publish while the engine is down, resume, the narrowed version is in force."""
    r.d("planner-1", "transfer_inventory", {**TRANSFER, "quantity": 1}, "r0")
    r.actl.publish(narrowed())
    r.tick(4)
    dep = r.restart()
    shown = dep.recovery_view()["authority"]["version"]
    return r.d("planner-1", "transfer_inventory", TRANSFER, "r1").status, shown


def nondeterministic(r):
    """class recovery_nondeterministic: two resumes of the same bytes must give byte-identical views (RC1)."""
    for i in range(12):
        r.d("planner-1", "transfer_inventory", {**TRANSFER, "quantity": 1}, f"r{i}")
    return canon_json(r.restart().recovery_view()) == canon_json(r.restart().recovery_view())


def as_denial(r):
    r.actl.outage(DEP, 2, 9)
    return r.d("planner-1", "transfer_inventory", TRANSFER, "r1")


def dropped_outbox(r):
    """class recovery_divergence (RC2): an undelivered intent survives the restart and is delivered after the heal."""
    r.ectl.outage("ERP", DEP, 2, 5)
    r.d("planner-1", "expedite_purchase_order", EXPEDITE, "e1")
    r.restart()
    r.tick(3)
    r.dep.dispatch_pending()
    r.tick(3)
    return r.dep.reconcile("e1", r.clock.now()).body["outcomes"][0]["state"]


def anchor_skipped(r):
    """class unanchored_ack: no OK while the anchor is down."""
    r.actl_anchor.partition(r.dep.service.stream, 2, 9, "drop")
    res = r.d("planner-1", "transfer_inventory", TRANSFER, "r1")
    return res.status, r.commits()


def test_fail_open_on_authority_outage(tmp_path):
    assert run(tmp_path, (), stale_commit) == ("UNAVAILABLE", ["r0"])
    status, commits = run(tmp_path, ("fail_open_on_authority_outage",), stale_commit)
    assert status == "OK" and "r1" in commits


def test_global_halt_on_fault(tmp_path):
    assert run(tmp_path, (), global_halt, ext=True) == "OK"
    assert run(tmp_path, ("global_halt_on_fault",), global_halt, ext=True) == "UNAVAILABLE"


def test_stale_cache_after_restart(tmp_path):
    status, shown = run(tmp_path, (), stale_restart)
    assert status == "DENIED" and shown is None
    status, shown = run(tmp_path, ("stale_cache_after_restart",), stale_restart)
    assert status == "OK" and shown == doc_digest(V0) and shown != doc_digest(narrowed())   # the stale version is treated as in force


def test_nondeterministic_recovery(tmp_path):
    assert run(tmp_path, (), nondeterministic, ext=True) is True
    assert run(tmp_path, ("nondeterministic_recovery",), nondeterministic, ext=True) is False


def test_dependency_failure_as_denial(tmp_path):
    clean = run(tmp_path, (), as_denial)
    assert (clean.status, clean.body["dependency"]) == ("UNAVAILABLE", "AUTH")
    assert run(tmp_path, ("dependency_failure_as_denial",), as_denial).status == "DENIED"


def test_outbox_dropped_on_restart(tmp_path):
    assert run(tmp_path, (), dropped_outbox, ext=True) == "RECONCILED_SUCCESS"
    assert run(tmp_path, ("outbox_dropped_on_restart",), dropped_outbox, ext=True) == "RECONCILED_FAILED"


def test_anchor_skipped_when_unavailable(tmp_path):
    assert run(tmp_path, (), anchor_skipped) == ("UNAVAILABLE", [])
    assert run(tmp_path, ("anchor_skipped_when_unavailable",), anchor_skipped) == ("OK", ["r1"])


def test_every_h29_mutant_has_a_test_here():
    names = {n for n in globals() if n.startswith("test_")}
    assert {f"test_{m}" for m in KNOWN["H29"]} <= names
