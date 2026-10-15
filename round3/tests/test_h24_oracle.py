"""H24 reference authority (r3_oracle/authority_v2.py): PROT-H24 issuance table, use rules, boundaries, parity."""
import ast
import copy
import random
from pathlib import Path

import pytest

from r3_harness.h23.corpus import load_specs
from r3_harness.h24 import gen_graph
from r3_oracle import scope_v2
from r3_oracle.authority_v2 import INF, RefAuthority, event
from r3_shared import authgraph
from r3_shared.authspec import validate_strict

OP = "expedite_purchase_order"
RES = [("PurchaseOrder", "PO-991")]
SRC = Path(__file__).resolve().parents[1] / "src" / "r3_oracle"


def base_spec(depth=3):
    ops, auth1 = load_specs()["manufacturing"]
    spec = copy.deepcopy(auth1)
    spec.update({"spec": "r3-authority-2", "max_delegation_depth": depth, "capabilities": [], "revoked": []})
    spec["grants"].append({"id": "g-pl-exp", "effect": "allow", "principal": {"id": "planner-1"}, "resource": {"any": True},
                           "operation": OP, "delegable": True, "origin": "neutral-extension"})
    return spec


def edge(eid, issuer, child, parent=None, ops=(OP,), keys=None, exp=None, redel=True):
    return {"id": eid, "issuer": issuer, "child": child, "parent": parent, "issued_at": 0, "expires_at": exp,
            "redelegable": redel, "scope": {"operations": list(ops), "resources": [{"type": "PurchaseOrder", "keys": keys}]}}


def ra_with(*edges, spec=None):
    ra = RefAuthority.from_spec(spec or base_spec())
    for i, e in enumerate(edges, 1):
        assert ra.issue_delegate(e, INF, 0).ok, e
        ra = ra.apply(event(i * 10, 0, "delegate", {"edge": e}))
    return ra


def test_scope_helpers_agree_with_the_shared_ones_on_generated_scopes():
    ops, _ = load_specs()["manufacturing"]
    rng = random.Random(3)
    names = [o["name"] for o in ops["operations"]]
    scopes = [gen_graph._scope(ops, names, rng) for _ in range(60)]
    scopes += [gen_graph._scope(ops, names, rng, rng.choice(scopes)) for _ in range(60)]
    keyset = [(t, k) for t, ks in gen_graph.seed_keys(ops).items() for k in ks]
    for a in scopes:
        for b in scopes[::7]:
            assert scope_v2.subset(a, b) == authgraph.scope_subset(a, b)
        for op in names:
            for res in ([], [keyset[rng.randrange(len(keyset))]], rng.sample(keyset, 2)):
                assert scope_v2.covers(a, op, res) == authgraph.scope_covers(a, op, res)


def test_digest_matches_the_shared_authority_digest():
    spec = base_spec()
    e1, e2 = edge("e1", "planner-1", "junior-1"), edge("e2", "junior-1", "senior-1", "e1")
    spec["capabilities"], spec["revoked"] = [e1, e2], ["e2"]
    assert RefAuthority.from_spec(spec).digest_at(None) == authgraph.authority_digest(spec)
    validate_strict(spec, load_specs()["manufacturing"][0])


ISSUANCE = [  # (name, edge builder over a prepared ra, expected (status, reason))
    ("schema", lambda: dict(edge("x", "planner-1", "junior-1"), extra=1), ("INVALID", "schema")),
    ("duplicate", lambda: edge("e1", "planner-1", "senior-1"), ("INVALID", "duplicate_edge")),
    ("cycle_self", lambda: edge("x", "planner-1", "planner-1"), ("INVALID", "delegation_cycle")),
    ("cycle_ancestor", lambda: edge("x", "junior-1", "planner-1", "e1"), ("INVALID", "delegation_cycle")),
    ("static_delegate", lambda: edge("x", "planner-1", "agent-1"), ("INVALID", "static_delegate")),
    ("unknown_principal", lambda: edge("x", "planner-1", "ghost"), ("INVALID", "unknown_principal")),
    ("unknown_parent", lambda: edge("x", "junior-1", "senior-1", "nope"), ("INVALID", "unknown_parent")),
    ("not_parent_holder", lambda: edge("x", "senior-1", "admin-1", "e1"), ("DENIED", "not_parent_holder")),
    ("not_redelegable", lambda: edge("x", "supervisor-1", "admin-1", "e3"), ("DENIED", "not_redelegable")),
    ("scope_amp_op", lambda: edge("x", "junior-1", "senior-1", "e1", ops=(OP, "reschedule_work_order")),
     ("DENIED", "scope_amplification")),
    ("scope_amp_keys_null", lambda: edge("x", "senior-1", "admin-1", "e2", keys=None), ("DENIED", "scope_amplification")),
    ("expiry_amp", lambda: edge("x", "senior-1", "admin-1", "e2", keys=["PO-991"], exp=None, redel=False),
     ("DENIED", "expiry_amplification")),
    ("root_not_delegable", lambda: edge("x", "junior-1", "senior-1"), ("DENIED", "scope_amplification")),
    ("already_expired", lambda: edge("x", "planner-1", "senior-1", exp=0), ("INVALID", "already_expired")),
    ("ok_attenuated", lambda: edge("x", "senior-1", "admin-1", "e2", keys=["PO-991"], exp=20, redel=False), ("OK", "")),
]


@pytest.mark.parametrize("name,mk,want", ISSUANCE, ids=[i[0] for i in ISSUANCE])
def test_issuance_table(name, mk, want):
    ra = ra_with(edge("e1", "planner-1", "junior-1"), edge("e2", "junior-1", "senior-1", "e1", keys=["PO-991", "PO-992"], exp=30),
                 edge("e3", "planner-1", "supervisor-1", redel=False))
    v = ra.issue_delegate(mk(), INF, 5)
    assert (v.status, v.reason) == want


def test_depth_exceeded_and_parent_invalid_after_revocation_and_expiry():
    ra = ra_with(edge("e1", "planner-1", "junior-1"), edge("e2", "junior-1", "senior-1", "e1"),
                 edge("e3", "senior-1", "admin-1", "e2", redel=True, exp=10), spec=base_spec(depth=3))
    assert ra.issue_delegate(edge("x", "admin-1", "supervisor-1", "e3"), INF, 3).reason == "depth_exceeded"
    assert ra.issue_delegate(edge("y", "admin-1", "supervisor-1", "e3"), INF, 3).status == "INVALID"
    ra2 = ra.apply(event(99, 4, "revoke", {"edge_id": "e1"}))
    assert ra2.issue_delegate(edge("z", "senior-1", "nobody-1", "e2", redel=False), INF, 4).reason == "parent_invalid"
    assert ra.issue_delegate(edge("w", "senior-1", "nobody-1", "e2", redel=False), INF, 4).ok  # not yet revoked
    spec2 = ra_with(edge("e1", "planner-1", "junior-1", exp=10), spec=base_spec(depth=5))
    assert spec2.issue_delegate(edge("q", "junior-1", "senior-1", "e1", exp=9), INF, 10).reason == "parent_invalid"  # expired at 10


def test_revoke_issuance_rules_and_already():
    ra = ra_with(edge("e1", "planner-1", "junior-1"), edge("e2", "junior-1", "senior-1", "e1"))
    assert ra.issue_revoke("planner-1", "e2", INF).ok  # upstream issuer can cut downstream
    assert ra.issue_revoke("junior-1", "e2", INF).ok
    assert (ra.issue_revoke("senior-1", "e2", INF).status, ra.issue_revoke("senior-1", "e2", INF).reason) == ("DENIED", "not_revoker")
    assert ra.issue_revoke("planner-1", "nope", INF).reason == "unknown_edge"
    ra = ra.apply(event(50, 1, "revoke", {"edge_id": "e2"}))
    assert ra.issue_revoke("planner-1", "e2", INF).reason == "already"


def test_use_rule_paths_boundaries_and_intersection():
    e1 = edge("e1", "planner-1", "junior-1", exp=10)
    e2 = edge("e2", "junior-1", "senior-1", "e1", keys=["PO-991"], exp=10)
    ra = ra_with(e1, e2)
    d = ra.decide("senior-1", "planner-1", OP, RES, 100, 9)
    assert d.allow and d.valid_paths == (("e1", "e2"),)
    assert not ra.decide("senior-1", "planner-1", OP, RES, 100, 10).allow  # expires_at = 10 is NOT usable at tick 10
    assert not ra.decide("senior-1", "planner-1", OP, [("PurchaseOrder", "PO-992")], 100, 5).allow  # intersection, not union
    assert not ra.decide("senior-1", None, OP, RES, 100, 5).allow  # edges never apply without on_behalf_of
    assert ra.decide("senior-1", "junior-1", OP, RES, 100, 5).reason == "no_valid_path"  # obo must name the ROOT
    assert not ra.decide("senior-1", "planner-1", "reschedule_work_order", [("WorkOrder", "WO-42")], 100, 5).allow
    r = ra.apply(event(60, 2, "revoke", {"edge_id": "e1"}))  # boundary: valid for seq <= 60, invalid for seq > 60
    assert r.decide("senior-1", "planner-1", OP, RES, 60, 3).allow
    assert not r.decide("senior-1", "planner-1", OP, RES, 61, 3).allow
    assert not r.decide("senior-1", "planner-1", OP, RES, None, 3).allow  # revoking e1 invalidates e2 (recursive)
    assert r.was_ever_valid("senior-1", "planner-1", OP, RES, 61, 3)
    assert not ra.was_ever_valid("senior-1", "planner-1", OP, [("PurchaseOrder", "PO-992")], 100, 5)


def test_several_valid_paths_root_recheck_and_deny_grants():
    ra = ra_with(edge("a1", "planner-1", "junior-1"), edge("a2", "planner-1", "senior-1"),
                 edge("b1", "junior-1", "admin-1", "a1"), edge("b2", "senior-1", "admin-1", "a2"))
    d = ra.decide("admin-1", "planner-1", OP, RES, 100, 1)
    assert d.allow and d.valid_paths == (("a1", "b1"), ("a2", "b2"))
    ra1 = ra.apply(event(70, 1, "revoke", {"edge_id": "a1"}))
    assert ra1.decide("admin-1", "planner-1", OP, RES, 100, 1).valid_paths == (("a2", "b2"),)
    spec = copy.deepcopy(base_spec())
    spec["grants"] = [g for g in spec["grants"] if not (g["principal"].get("role") == "planner" and g["operation"] == OP)
                      and g["id"] != "g-pl-exp"]
    lost = ra.apply(event(80, 2, "set_authority", {"spec": {**spec, "capabilities": [], "revoked": []}}))
    assert lost.decide("admin-1", "planner-1", OP, RES, 100, 2).reason == "root_lost_authority"  # root re-check
    deny = copy.deepcopy(base_spec())
    deny["grants"].append({"id": "d1", "effect": "deny", "principal": {"id": "junior-1"}, "resource": {"any": True},
                           "operation": OP, "delegable": False, "origin": "neutral-extension"})
    dd = ra.apply(event(90, 3, "set_authority", {"spec": {**deny, "capabilities": [], "revoked": []}}))
    assert dd.decide("admin-1", "planner-1", OP, RES, 100, 3).valid_paths == (("a2", "b2"),)  # (f) deny on an issuer


def test_static_delegates_keep_the_h23_rule_and_never_use_edges():
    ra = ra_with(edge("e1", "planner-1", "junior-1"))
    d = ra.decide("agent-1", "planner-1", "transfer_inventory", [("Warehouse", "WH-A"), ("Warehouse", "WH-B"), ("Part", "PX-17")], 100, 1)
    assert d.valid_paths == () and d.reason  # decided by r3_oracle.authority, no path
    assert not ra.decide("agent-1", "junior-1", OP, RES, 100, 1).allow


def test_apply_is_pure_and_events_must_advance():
    ra = ra_with(edge("e1", "planner-1", "junior-1"))
    n = len(ra.events)
    ra2 = ra.apply(event(70, 1, "revoke", {"edge_id": "e1"}))
    assert len(ra.events) == n and len(ra2.events) == n + 1
    assert ra.decide("junior-1", "planner-1", OP, RES, 100, 1).allow and not ra2.decide("junior-1", "planner-1", OP, RES, 100, 1).allow
    with pytest.raises(ValueError):
        ra2.apply(event(5, 1, "revoke", {"edge_id": "e1"}))


def test_reference_authority_reads_no_clock_and_imports_no_variant():
    for name in ("authority_v2.py", "scope_v2.py"):
        for n in ast.walk(ast.parse((SRC / name).read_text())):
            mods = [a.name for a in n.names] if isinstance(n, ast.Import) else (
                [n.module or ""] if isinstance(n, ast.ImportFrom) and n.level == 0 else [])
            assert not [m for m in mods if m.split(".")[0] in ("time", "datetime", "paladin", "conventional", "r3_harness")]
    from r3_harness.h24.evaluator import oracle_independent
    assert oracle_independent() == (True, [])
