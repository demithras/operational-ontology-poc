"""PROT-H29 R29-0, R29-1, R29-3, R29-5(c), R29-6, R29-7 on the Paladin decision plane (in-process deployment over REAL services).
Each requirement has a positive and a negative; stale-sensitivity is engineered (the old version permits, the new one refuses)."""
import json
import re
from pathlib import Path

import pytest

from g5_rig import DEP, EXP, RES, TR, G5Rig, narrowed
from r3_shared.authsvc import doc_digest, in_force
from r3_shared.anchor import AnchorUnavailable
from r3_shared.recovery import validate_recovery_view, validate_reply

DEPREPLY = ("UNAVAILABLE", "dependency_unavailable")


@pytest.fixture
def rig():
    r = G5Rig()
    yield r
    r.finish()


def dep_of(res):
    return res.body.get("dependency")


def a_of(rig, t):
    return in_force(rig.actl.log()["versions"], t)


def test_r29_0_lease_is_renewed_on_every_decision_and_honoured_inside_its_window(rig):
    assert rig.call("planner-1", "transfer_inventory", TR, "a1").status == "OK"
    leases = rig.actl.log()["leases"]
    assert [(l["granted_tick"], l["lease_until"]) for l in leases] == [(0, 4)]
    rig.tick()
    assert rig.call("planner-1", "reschedule_work_order", RES, "a2").status == "OK"
    assert [(l["granted_tick"], l["lease_until"]) for l in rig.actl.log()["leases"]] == [(0, 4), (1, 5)]   # renewed, not cached
    rig.actl.outage(DEP, 2, 9, "drop")
    rig.tick()                                                                                  # t=2: AUTH down, lease valid to 5
    assert rig.call("planner-1", "expedite_purchase_order", EXP, "a3").status == "OK"          # SAFE_TO_RUN: must progress
    rig.tick(2)                                                                                 # t=4 < 5
    assert rig.dep.read(rig.token("planner-1"), "list", {"type": "Part"}).status == "OK"
    rig.tick()                                                                                  # t=5 == lease_until: strict upper bound
    n = len(rig.commits())
    res = rig.call("planner-1", "transfer_inventory", {**TR, "quantity": 1}, "a4")
    assert (res.status, res.body) == ("UNAVAILABLE", {"reason": "dependency_unavailable", "dependency": "AUTH"})
    validate_reply(res.status, res.body)
    assert len(rig.commits()) == n                                                              # zero effects
    assert [c for c in rig.commits() if c in ("a1", "a2", "a3")] == ["a1", "a2", "a3"]


def test_r29_1_commit_is_bound_to_the_version_in_force_and_stale_use_is_refused(rig):
    narrow = narrowed(rig.auth0)
    assert rig.call("planner-1", "transfer_inventory", TR, "s1").status == "OK"
    d1 = rig.actl.publish(narrow)                                                               # lease runs to 4 -> effective at 4
    versions = rig.actl.log()["versions"]
    assert [v["effective_tick"] for v in versions] == [0, 4]
    for t in (1, 2, 3):
        rig.tick()
        res = rig.call("planner-1", "transfer_inventory", {**TR, "quantity": t + 1}, f"s{t + 1}")
        assert res.status == "OK"                                                               # still the old version, legitimately
    rig.tick()                                                                                  # t=4: the narrowed version is in force
    assert a_of(rig, 4) == d1
    res = rig.call("planner-1", "transfer_inventory", {**TR, "quantity": 9}, "s9")
    assert res.status == "DENIED"                                                               # stale-sensitive: old OK, new DENIED
    marks = [x["data"] for x in rig.reader.log(0) if x["kind"] == "mark" and x["ref"] == "commit"]
    stamps = {m["request_id"]: m["authority_version"] for m in marks}
    for rid, t in (("s1", 0), ("s2", 1), ("s3", 2), ("s4", 3)):
        assert stamps[rid] == a_of(rig, t) == doc_digest(rig.auth0)                           # bound version == A(t)
    assert "s9" not in stamps


def test_r29_1_negative_outage_after_publish_never_decides_under_the_old_version(rig):
    rig.call("planner-1", "transfer_inventory", TR, "o1")
    rig.actl.publish(narrowed(rig.auth0))
    rig.actl.outage(DEP, 1, 12, "drop")
    for t in (1, 2, 3):
        rig.tick()
        assert rig.call("planner-1", "transfer_inventory", {**TR, "quantity": t + 1}, f"o{t + 1}").status == "OK"   # inside the lease window
    rig.tick()                                                                                  # t=4: lease expired, new version in force, AUTH down
    res = rig.call("planner-1", "transfer_inventory", {**TR, "quantity": 7}, "o7")
    assert (res.status, dep_of(res)) == DEPREPLY[:1] + ("AUTH",)
    assert "o7" not in rig.commits()


def test_r29_3_read_is_the_low_view_or_unavailable_never_a_stale_view(rig):
    tok = rig.token("planner-1")
    ok = rig.dep.read(tok, "list", {"type": "Part"})
    assert ok.status == "OK"
    rig.actl.outage(DEP, 1, 9, "drop")
    rig.tick(3)
    assert rig.dep.read(tok, "list", {"type": "Part"}).status == "OK"                          # t=3 < lease_until 4: the lease window
    rig.tick()
    res = rig.dep.read(tok, "list", {"type": "Part"})                                          # t=4 == lease_until: strict, expired
    assert (res.status, res.body) == ("UNAVAILABLE", {"reason": "dependency_unavailable", "dependency": "AUTH"})


def test_r29_6_anchor_down_blocks_with_zero_effects_and_names_the_anchor(rig):
    stream = rig.dep._c.prov.stream
    rig.nctl.partition(stream, 1, 5, "drop")
    rig.tick()
    n = len(rig.commits())
    res = rig.call("planner-1", "transfer_inventory", TR, "n1")
    assert (res.status, res.body) == ("UNAVAILABLE", {"reason": "dependency_unavailable", "dependency": "ANCHOR"})
    assert len(rig.commits()) == n and rig.dep._c.ledger.get("n1") is None
    # a refusal needs the anchor too: policy denial is anchored, so it is UNAVAILABLE ANCHOR, never DENIED naming a dependency
    res = rig.call("junior-1", "expedite_purchase_order", EXP, "n2")
    assert res.status == "UNAVAILABLE" and dep_of(res) == "ANCHOR"
    rig.tick(4)                                                                                 # window over
    assert rig.call("planner-1", "transfer_inventory", TR, "n1").status == "OK"                # the same request id commits exactly once now
    assert rig.commits().count("n1") == 1


def test_r29_6_denied_never_names_a_dependency_and_input_errors_stay_decidable(rig):
    res = rig.call("junior-1", "expedite_purchase_order", EXP, "d1")                          # healthy: a real policy denial
    assert res.status == "DENIED"
    validate_reply("DENIED", res.body)
    rig.actl.outage(DEP, 1, 20, "drop")
    rig.tick(6)
    bad = rig.call("planner-1", "transfer_inventory", {"part": 7}, "d2")                       # schema error is decidable without AUTH
    assert (bad.status, bad.body) == ("INVALID", {"reason": "schema_invalid"})
    nobody = rig.dep.direct("not-a-token", "transfer_inventory", TR, request_id="d3")           # unauthenticated: never DENIED while blocked
    assert nobody.status == "UNAVAILABLE" and dep_of(nobody) == "AUTH"
    ok_shape = rig.call("junior-1", "expedite_purchase_order", EXP, "d4")
    assert ok_shape.status == "UNAVAILABLE"                                                     # a would-be denial is not decided without AUTH


def test_r29_6_commit_unconfirmed_by_the_anchor_is_in_doubt_and_redelivery_completes_it(rig):
    c, real = rig.dep._c, rig.dep._c.prov.a

    class LostReply:
        """reply_lost after the append was applied (the server applied it, the client sees DependencyUnavailable)."""
        def __getattr__(self, n):
            return getattr(real, n)

        def append(self, *a, **k):
            real.append(*a, **k)
            raise AnchorUnavailable("test")
    c.prov.a = LostReply()
    res = rig.call("planner-1", "transfer_inventory", TR, "i1")
    assert (res.status, res.body) == ("UNKNOWN", {"reason": "in_doubt"})
    validate_reply(res.status, res.body)
    assert rig.commits().count("i1") == 1
    c.prov.a = real
    again = rig.call("planner-1", "transfer_inventory", TR, "i1")                              # the anchor holds the entry: the original OK
    assert again.status == "OK" and again.body.get("replayed") is True
    assert rig.commits().count("i1") == 1                                                       # R29-5(c): never a second commit


def test_r29_6_commit_never_anchored_stays_in_doubt_not_ok(rig):
    c, real = rig.dep._c, rig.dep._c.prov.a

    class Dropped:
        def __getattr__(self, n):
            return getattr(real, n)

        def append(self, *a, **k):
            raise AnchorUnavailable("test")      # the append never reached the anchor
    c.prov.a = Dropped()
    assert rig.call("planner-1", "transfer_inventory", TR, "i2").status == "UNKNOWN"
    c.prov.a = real
    for _ in range(2):
        again = rig.call("planner-1", "transfer_inventory", TR, "i2")
        assert (again.status, again.body) == ("UNKNOWN", {"reason": "in_doubt"})               # an OK needs an anchor entry (R29-4)
    assert rig.commits().count("i2") == 1


def test_r29_5_redelivery_after_ok_returns_the_original_decision_without_a_second_commit(rig):
    first = rig.call("planner-1", "transfer_inventory", TR, "r1")
    assert first.status == "OK"
    for _ in range(3):
        again = rig.call("planner-1", "transfer_inventory", TR, "r1")
        assert again.status == "OK" and again.body.get("replayed") is True
    assert rig.commits().count("r1") == 1


def test_dependency_status_and_recovery_view_forms(rig):
    rig.call("planner-1", "transfer_inventory", TR, "v1")
    st = rig.dep.dependency_status()
    assert st["AUTH"] == "UP" and st["ANCHOR"] == "UP" and set(st) >= {"OBS", "EXT:WMS", "EXT:ERP", "EXT:MES"}
    v = validate_recovery_view(rig.dep.recovery_view())
    assert [c["request_id"] for c in v["committed"]] == ["v1"] and v["intents"][0]["system"] == "WMS"
    assert v["authority"] == {"version": doc_digest(rig.auth0), "lease_until": 4}


def test_graph_is_read_as_data_no_dependency_literals_of_the_domains_in_variant_code():
    """C29-7: the frozen graph names every operation, system and external node; no module of the variant spells one of them."""
    from g5_rig import GRAPH_PATH
    g = json.loads(GRAPH_PATH.read_text())
    words = set(g["operations"]["manufacturing"]) | set(g["operations"]["project"]) | {"WMS", "ERP", "MES", "REGISTRY", "NOTIFY", "GEN-NULL"}
    src = Path(__file__).resolve().parents[2] / "src" / "paladin"
    mine = [src / "depgraph.py", src / "leasing.py", src / "continuity.py"]
    for f in mine:
        text = f.read_text()
        hits = [w for w in words if re.search(rf"[\"']{re.escape(w)}[\"']", text)]
        assert hits == [], (f.name, hits)
    assert re.search(r"[\"']EXT:", (src / "continuity.py").read_text()) is None
