"""The four H24 mutants (constructor-activated, at the real bug sites): each changes behaviour in a way a clean build never does."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from g2_rig import G2Rig, edge  # noqa: E402


def mk(tmp_path, name, mutants):
    d = tmp_path / name
    d.mkdir()
    return G2Rig(d, mutants=mutants)


def effect_commits(r, rid):
    return [m for m in r.log() if m["kind"] == "mark" and m["ref"] == "commit" and m["data"]["request_id"] == rid]


def scenario_amplification(r):
    keys = [{"type": "Warehouse", "keys": ["WH-C"]}, {"type": "Part", "keys": None}]
    assert r.delegate("planner-1", edge("p", "planner-1", "ag-1", resources=keys)).status == "OK"
    wide = r.delegate("ag-1", edge("c", "ag-1", "ag-2", "p"))  # child scope = every warehouse
    use = r.transfer("ag-2", "planner-1", rid="amp")  # TR touches WH-B, outside the parent's scope
    return wide.status, use.status, len(effect_commits(r, "amp"))


def test_non_attenuating_delegation(tmp_path):
    assert scenario_amplification(mk(tmp_path, "clean", ())) == ("DENIED", "DENIED", 0)
    assert scenario_amplification(mk(tmp_path, "mut", ("non_attenuating_delegation",))) == ("OK", "OK", 1)  # forbidden effect committed


def scenario_stale(r):
    assert r.delegate("planner-1", edge("e", "planner-1", "ag-1")).status == "OK"
    assert r.transfer("ag-1", "planner-1", rid="a").status == "OK"
    assert r.revoke("planner-1", "e").status == "OK"
    return r.transfer("ag-1", "planner-1", rid="b").status, len(effect_commits(r, "b"))


def test_stale_authority_cache(tmp_path):
    assert scenario_stale(mk(tmp_path, "clean", ())) == ("DENIED", 0)
    assert scenario_stale(mk(tmp_path, "mut", ("stale_authority_cache",))) == ("OK", 1)  # decision cached across the revocation


def scenario_reorder(r):
    assert r.delegate("planner-1", edge("e", "planner-1", "ag-1")).status == "OK"
    assert r.revoke("planner-1", "e", rid="rv").status == "OK"  # acknowledged
    first = r.transfer("ag-1", "planner-1", rid="after-ack").status  # returned AFTER the revoke returned OK
    second = r.transfer("ag-1", "planner-1", rid="later").status
    return first, second


def test_revoke_commit_reorder(tmp_path):
    assert scenario_reorder(mk(tmp_path, "clean", ())) == ("DENIED", "DENIED")
    r = mk(tmp_path, "mut", ("revoke_commit_reorder",))
    assert scenario_reorder(r) == ("OK", "DENIED")  # the effect slipped in between the ack and the applied revoke
    log = r.log()
    rev = next(m["seq"] for m in log if m["kind"] == "mark" and m["ref"] == "authority" and m["data"].get("op") == "revoke")
    assert effect_commits(r, "after-ack")[0]["seq"] < rev  # linearizability violated: revoke returned before it committed


def scenario_expiry(r):
    assert r.delegate("planner-1", edge("e", "planner-1", "ag-1", expires=5)).status == "OK"
    r.clock.advance(5)
    return r.transfer("ag-1", "planner-1", rid="at-expiry").status


def test_expiry_inclusive(tmp_path):
    assert scenario_expiry(mk(tmp_path, "clean", ())) == "DENIED"
    assert scenario_expiry(mk(tmp_path, "mut", ("expiry_inclusive",))) == "OK"
