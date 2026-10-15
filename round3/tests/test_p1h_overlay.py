"""P1h workload overlay generator (PROT-H30 1.9): deterministic, frozen files reproducible, every state-checkable ops-spec invariant holds,
authority strictly valid with working delegation chains, reachable through ops-spec operations, and every check has a known-negative."""
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from r3_harness.h26 import invariants as inv
from r3_shared import authspec
from r3_harness.h30 import overlay_gen as G
from r3_harness.h30 import validate as C

ROUND3 = Path(__file__).resolve().parents[1]
DOMAINS = G.DOMAINS


@pytest.fixture(scope="module", params=DOMAINS)
def ov(request):
    return C.load_overlay(request.param)


def test_frozen_files_are_exactly_what_the_generator_produces():
    r = subprocess.run([sys.executable, str(ROUND3 / "scripts" / "gen_h30_overlay.py"), "--check"], capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin"})
    assert r.returncode == 0, r.stdout + r.stderr


def test_generator_is_deterministic_and_base_cluster_is_the_frozen_seed(ov):
    again = G.build_overlay(ov["domain"])
    assert G.canon(again) == G.canon(ov)
    base = json.loads((ROUND3 / ov["inputs"]["ops"]["path"]).read_text())["seed"]
    n = len(base["objects"])
    assert ov["ops_seed"]["objects"][:n] == base["objects"] and ov["ops_seed"]["links"][:len(base["links"])] == base["links"]


def test_overlay_is_larger_on_every_axis_the_spec_names(ov):
    d = ov["domain"]
    auth0 = json.loads((ROUND3 / ov["inputs"]["authority"]["path"]).read_text())
    seed0 = json.loads((ROUND3 / ov["inputs"]["ops"]["path"]).read_text())["seed"]
    a = ov["authority"]
    assert len(a["principals"]) >= 3 * len(auth0["principals"])
    assert sum(1 for p in a["principals"] if p["kind"] == "agent") > sum(1 for p in auth0["principals"] if p["kind"] == "agent")
    assert len(a["service_accounts"]) == 1 + (len(auth0["service_accounts"]) - 1) * (G.CLUSTERS + 1)       # svc-core is shared, adapters cloned
    assert len(a["capabilities"]) == 2 * len(ov["ids"]["clusters"]) and len(a["delegations"]) == len(auth0["delegations"]) * (G.CLUSTERS + 1)
    assert len(ov["ids"]["clusters"]) == G.CLUSTERS + 1
    shared = G.SHARED_TYPES[d]
    cloned0 = sum(1 for o in seed0["objects"] if o["type"] not in shared)
    assert len(ov["ops_seed"]["objects"]) == len(seed0["objects"]) + cloned0 * G.CLUSTERS
    if d == "manufacturing":                      # frozen seed: 5 lots (WMS) + 2 purchase orders (ERP) + 2 work orders (MES) per cluster
        assert sum(len(v) for v in ov["ids"]["external_targets"].values()) == 9 * (G.CLUSTERS + 1)
    else:
        assert ov["ids"]["external_targets"] == {} and "REGISTRY" in ov["ids"]["external_systems"]   # project targets come from target rules


def test_admissibility_of_the_frozen_overlay_is_clean(ov):
    assert G.check_overlay(ov) == []


def test_every_ops_spec_invariant_is_covered_and_holds(ov):
    ops = G.overlay_ops(ov)
    ids = {i["id"] for i in ops["invariants"]}
    assert ids <= set(inv.STATE) | set(inv.NON_STATE)
    assert inv.violations(ops, G._snapshot(ov["ops_seed"])) == []


def test_authority_is_strictly_valid_and_chains_decide_as_intended(ov):
    ops = G.overlay_ops(ov)
    authspec.validate_strict(ov["authority"], ops)               # schema + graph + disclosure
    from r3_oracle.authority_v2 import RefAuthority
    from r3_oracle.constitution import to_v2
    ra = RefAuthority.from_spec(to_v2(ov["authority"]))
    ch = G.CHAIN[ov["domain"]]
    for tag in ov["ids"]["clusters"]:
        e1 = next(e for e in ov["authority"]["capabilities"] if e["id"] == f"e-{tag}-1")
        e2 = next(e for e in ov["authority"]["capabilities"] if e["id"] == f"e-{tag}-2")
        assert ra.depth_of(e2["id"]) == 2 and e2["scope"]["operations"] == ch["ops2"]
        res = [(r["type"], r["keys"][0]) for r in e2["scope"]["resources"]]
        assert ra.decide(e2["child"], e1["issuer"], ch["ops2"][0], res, None, 0).allow
        assert not ra.decide(e2["child"], e1["issuer"], "no_such_operation", res, None, 0).allow


def test_ids_are_unique_and_every_task_visible_id_exists(ov):
    refs = [f"{o['type']}:{o['key']}" for o in ov["ops_seed"]["objects"]]
    assert len(refs) == len(set(refs))
    assert {f"{t}:{k}" for t, ks in ov["ids"]["resources"].items() for k in ks} == set(refs)
    pids = [p["id"] for p in ov["authority"]["principals"]]
    assert len(pids) == len(set(pids)) and set(sum((v for k, v in ov["ids"]["principals"].items() if k != "service" and k != "hostile"), [])) <= set(pids)


def test_reachability_through_ops_spec_operations(ov):
    r = G.reachability(ov)
    assert len(r["reachable"]) >= 0.6 * len(r["required"])
    frozen_unreachable = set(ov["reachability"]["unreachable_in_frozen_seed"])
    assert {u for u in r["unreachable"] if "_c" not in u} <= frozen_unreachable      # clones are unreachable only if their frozen original is
    if ov["domain"] == "manufacturing":
        assert r["unreachable"] == []                                                # every warehouse / part / PO / work order takes part in a request


# ---- known negatives: each admissibility check goes red on a broken overlay -------------------------------------------------------
def _mut(ov, f):
    o = copy.deepcopy(ov)
    f(o)
    return G.check_overlay(o)


def test_negative_invariant_violation_is_caught():
    ov = C.load_overlay("manufacturing")
    def f(o):
        lot = next(x for x in o["ops_seed"]["objects"] if x["type"] == "InventoryLot" and x["key"].endswith("_c2"))
        lot["props"]["reserved"] = lot["props"]["onHand"] + 1
    bad = _mut(ov, f)
    assert any("invariant violated" in b and "covers-reserved" in b for b in bad), bad


def test_negative_changed_input_hash_is_caught():
    ov = C.load_overlay("project")
    bad = _mut(ov, lambda o: o["inputs"]["ops"].__setitem__("sha256", "0" * 64))
    assert any("input ops changed" in b for b in bad)


def test_negative_dangling_link_and_missing_relation_target_are_caught():
    ov = C.load_overlay("manufacturing")
    bad = _mut(ov, lambda o: o["ops_seed"]["links"].append({"link_type": "InventoryLot_warehouse", "src": "InventoryLot:GHOST", "dst": "Warehouse:WH-A"}))
    assert any("dangling link" in b for b in bad)
    def f(o):
        p = next(p for p in o["authority"]["principals"] if p["id"] == "planner-1_c3")
        p["relations"].append({"type": "Warehouse", "key": "WH-NOPE", "relation": "planner"})
    assert any("relation on missing object" in b for b in _mut(ov, f))


def test_negative_amplifying_chain_is_rejected_by_strict_validation():
    ov = C.load_overlay("manufacturing")
    def f(o):
        e2 = next(e for e in o["authority"]["capabilities"] if e["id"] == "e-c1-2")
        e2["scope"]["resources"][0]["keys"] = e2["scope"]["resources"][0]["keys"] + ["WH-A"]      # outside the parent's scope
    assert any("spec validation" in b and "amplification" in b for b in _mut(ov, f))


def test_negative_unreachable_clone_is_caught():
    ov = C.load_overlay("project")
    def f(o):
        h = next(x for x in o["ops_seed"]["objects"] if x["key"] == "H-A_c2")
        h["props"]["phase"] = "SUPERSEDED"            # edit_threshold needs a DRAFT governed hypothesis: T-A_c2 loses its only way in
    bad = _mut(ov, f)
    assert any("reachability of Threshold:T-A_c2 differs from its frozen counterpart Threshold:T-A" in b for b in bad), bad


def test_negative_reachability_engine_is_not_vacuous():
    ov = C.load_overlay("manufacturing")
    o = copy.deepcopy(ov)
    o["authority"]["grants"] = [g for g in o["authority"]["grants"] if g["operation"] not in ("expedite_purchase_order", "*")]
    r = G.reachability(o)
    assert any(u.startswith("PurchaseOrder:") for u in r["unreachable"]) and G.reachability(ov)["unreachable"] == []


def test_negative_a_broken_chain_leaf_is_caught():
    ov = C.load_overlay("project")
    def f(o):
        e2 = next(e for e in o["authority"]["capabilities"] if e["id"] == "e-c2-2")
        e2["scope"]["operations"] = ["start_run"]                       # the leaf can no longer do what the checker expects (attach_evidence)
    assert any("leaf agent denied inside its own scope" in b for b in _mut(ov, f))
