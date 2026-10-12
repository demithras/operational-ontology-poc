"""R29-8..R29-11: deterministic recovery (resume = a NEW Service over the surviving durable stores). Hand-written expectations."""
import json
import shutil
import sqlite3

import pytest

from conv_g5_util import DEP, EXPEDITE, TRANSFER, V0, make_g5, narrowed, stop_all
from r3_shared.anchor import AnchorUnavailable
from r3_shared.authsvc import doc_digest
from r3_shared.faultplane import CanonicalStateLost
from r3_shared.recovery import canon_json, validate_recovery_view
from r3_shared.world import WorldStore


@pytest.fixture
def rig(tmp_path):
    r = make_g5(tmp_path / "r", ext=True)
    yield r
    stop_all()


def view(dep):
    return validate_recovery_view(dep.recovery_view())


def test_recovery_view_form_and_content(rig):
    rig.d("planner-1", "transfer_inventory", TRANSFER, "r1")
    rig.d("planner-1", "expedite_purchase_order", EXPEDITE, "e1")
    v = view(rig.dep)
    assert [c["request_id"] for c in v["committed"]] == ["r1", "e1"]
    assert v["committed"][0]["authority_version"] == doc_digest(V0)
    assert [(i["request_id"], i["system"], i["chain_ids"]) for i in v["intents"]] == [("e1", "ERP", 1), ("r1", "WMS", 1)]
    assert v["authority"] == {"version": doc_digest(V0), "lease_until": rig.clock.now() + 4}


def test_resume_view_is_byte_identical_for_two_hosts_and_authority_unverified(rig):
    rig.d("planner-1", "transfer_inventory", TRANSFER, "r1")
    rig.d("planner-1", "expedite_purchase_order", EXPEDITE, "e1")
    leases = len(rig.actl.log()["leases"])
    head = rig.anchor.head(rig.dep.service.stream)
    a, b = rig.restart(), rig.restart()
    assert canon_json(view(a)) == canon_json(view(b))
    assert view(a)["authority"] == {"version": None, "lease_until": None}   # a fresh process holds no lease, trusts no cache
    assert len(rig.actl.log()["leases"]) == leases and rig.anchor.head(rig.dep.service.stream) == head   # no dependency I/O


def test_resume_over_byte_copies_gives_equal_views(rig, tmp_path):
    rig.d("planner-1", "transfer_inventory", TRANSFER, "r1")
    rig.d("planner-1", "expedite_purchase_order", EXPEDITE, "e1")
    cp = tmp_path / "copy"
    cp.mkdir()
    for f in list(rig.tmp.glob("w.db*")) + list(rig.tmp.glob("hist.db*")):   # WAL siblings are part of the durable bytes
        shutil.copy(f, cp / f.name)
    from conventional.variant import ConventionalVariant
    from r3_shared.histstore import HistoryStore
    from r3_shared.world import WorldStore as WS
    ws = WS(cp / "w.db", clock=rig.clock)
    other = ConventionalVariant().deploy("manufacturing", ws.handle_factory(), rig.idp.verifier(), rig.ops, V0, rig.clock, None,
                                         HistoryStore(str(cp / "hist.db")), rig.anchor, None, rig.binding, rig.source(), True)
    assert canon_json(view(other)) == canon_json(view(rig.restart()))


def test_redelivery_after_resume_returns_the_original_with_no_new_rows(rig):
    first = rig.d("planner-1", "transfer_inventory", TRANSFER, "r1")
    n = len(rig.reader.log())
    rig.restart()
    again = rig.d("planner-1", "transfer_inventory", TRANSFER, "r1", fresh=False)
    assert (again.status, again.body.get("effects")) == (first.status, first.body["effects"])
    assert again.body["replayed"] is True
    assert rig.commits().count("r1") == 1 and len([x for x in rig.reader.log() if x["kind"] != "mark"]) == len(
        [x for x in rig.reader.log()[:n] if x["kind"] != "mark"])


def test_resume_with_nothing_durable_raises_canonical_state_lost(rig, tmp_path):
    empty = WorldStore(tmp_path / "empty.db", clock=rig.clock)
    from conventional.variant import ConventionalVariant
    from r3_shared.histstore import HistoryStore
    with pytest.raises(CanonicalStateLost):
        ConventionalVariant().deploy("manufacturing", empty.handle_factory(), rig.idp.verifier(), rig.ops, V0, rig.clock, None,
                                     HistoryStore(str(tmp_path / "h2.db")), rig.anchor, None, None, rig.source(), True)


class FailingAppend:
    """Wraps the AnchorClient: append applied-or-not, then the client sees AnchorUnavailable (reply_lost / drop mid-decision)."""

    def __init__(self, inner, apply):
        self.inner, self.apply, self.armed = inner, apply, True

    def __getattr__(self, n):
        return getattr(self.inner, n)

    def append(self, *a):
        if self.armed:
            self.armed = False
            if self.apply:
                self.inner.append(*a)
            raise AnchorUnavailable("injected")
        return self.inner.append(*a)


@pytest.mark.parametrize("applied", [False, True])
def test_anchor_lost_after_commit_is_in_doubt_and_redelivery_completes_it(rig, applied):
    svc = rig.dep.service
    svc.anchor = svc.prov.anchor = FailingAppend(rig.anchor, applied)
    res = rig.d("planner-1", "transfer_inventory", TRANSFER, "r1")
    assert (res.status, res.body) == ("UNKNOWN", {"reason": "in_doubt"})
    assert rig.commits() == ["r1"]
    again = rig.d("planner-1", "transfer_inventory", TRANSFER, "r1")        # redelivery finishes the anchoring first
    assert again.status == "OK" and again.body["replayed"] is True
    entry = rig.anchor.lookup(svc.stream, "r1")
    assert entry is not None and rig.dep.replay("r1").status == "VERIFIED"
    assert rig.dep.service.prov.history.get(f"env/{entry['seq']:010d}") is not None
    assert rig.commits() == ["r1"] and rig.anchor.head(svc.stream)["seq"] == 1


def test_unanchored_commit_is_completed_by_the_first_governed_call_after_resume(rig):
    svc = rig.dep.service
    svc.anchor = svc.prov.anchor = FailingAppend(rig.anchor, False)
    rig.d("planner-1", "transfer_inventory", TRANSFER, "r1")
    assert rig.anchor.lookup(svc.stream, "r1") is None
    rig.restart()
    rig.d("planner-1", "transfer_inventory", {**TRANSFER, "quantity": 1}, "r2")
    assert rig.anchor.lookup(svc.stream, "r1") is not None and rig.anchor.lookup(svc.stream, "r2") is not None
    assert rig.dep.replay("r1").status == "VERIFIED"


def test_outbox_is_redelivered_after_resume_exactly_once(rig):
    rig.ectl.outage("ERP", DEP, 2, 5)
    assert rig.d("planner-1", "expedite_purchase_order", EXPEDITE, "e1").status == "OK"
    rig.restart()
    rig.tick(3)                                                  # tick 5: healed
    assert rig.dep.dispatch_pending().body["submitted"] == 1
    rig.dep.dispatch_pending()
    rig.tick(3)
    assert rig.dep.reconcile("e1", rig.clock.now()).body["outcomes"][0]["state"] == "RECONCILED_SUCCESS"
    con = sqlite3.connect(f"file:{rig.tmp / 'ext' / 'external.db'}?mode=ro", uri=True)
    assert con.execute("SELECT COUNT(*) FROM effects").fetchone()[0] == 1
    assert view(rig.dep)["intents"][0]["chain_ids"] == 1


def test_authority_published_while_engine_down_is_not_served_stale_after_resume(rig):
    rig.d("planner-1", "transfer_inventory", TRANSFER, "r1")
    rig.actl.publish(narrowed())
    rig.tick(4)                                                   # in force from tick 6
    dep = rig.restart()
    assert view(dep)["authority"]["version"] is None
    denied = rig.d("planner-1", "transfer_inventory", TRANSFER, "r2")
    assert (denied.status, denied.body["reason"]) == ("DENIED", "no_matching_allow")
    assert view(dep)["authority"]["version"] == doc_digest(narrowed())


def test_approvals_open_listed_until_consumed(rig):
    big = {"po_id": "PO-991", "expedite_fee": 900}
    assert rig.dep.approve(rig.token("supervisor-1"), "expedite_purchase_order", big, "planner-1").status == "OK"
    assert len(view(rig.restart())["approvals_open"]) == 1
    assert rig.d("planner-1", "expedite_purchase_order", big, "e9").status == "OK"
    assert view(rig.dep)["approvals_open"] == []
