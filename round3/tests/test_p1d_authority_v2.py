import copy
import json
import pytest
from r3_shared.authgraph import authority_digest, edge_path, scope_covers, scope_subset
from r3_shared.authspec import load_auth_spec, validate_strict
from r3_shared.opsspec import load_ops_spec

OPS = load_ops_spec("manufacturing")


def sc(ops, *res):
    return {"operations": list(ops), "resources": [{"type": t, "keys": k} for t, k in res]}


def edge(id_, issuer, child, parent=None, scope=None, exp=None, redel=True):
    return {"id": id_, "issuer": issuer, "child": child, "parent": parent, "issued_at": 0, "expires_at": exp,
            "redelegable": redel, "scope": scope or sc(["transfer_inventory", "expedite_purchase_order"], ("Part", None))}


@pytest.fixture
def base():
    s = copy.deepcopy(load_auth_spec("manufacturing"))
    s.update({"spec": "r3-authority-2", "max_delegation_depth": 3, "capabilities": [], "revoked": []})
    return s


def v2(base, *edges, revoked=()):
    return {**base, "capabilities": list(edges), "revoked": list(revoked)}


def ok_chain():
    return [edge("e1", "planner-1", "junior-1"), edge("e2", "junior-1", "supervisor-1", "e1", sc(["transfer_inventory"], ("Part", ["P1"])), 9),
            edge("e3", "supervisor-1", "senior-1", "e2", sc(["transfer_inventory"], ("Part", ["P1"])), 5)]


def test_accepts_valid_graph_and_v1_still_valid(base):
    assert validate_strict(v2(base, *ok_chain()), OPS)["spec"] == "r3-authority-2"
    validate_strict(v2(base), OPS)
    validate_strict(load_auth_spec("manufacturing"), OPS)


REJECT = {
    "duplicate_id": (lambda: [edge("e1", "planner-1", "junior-1"), edge("e1", "planner-1", "senior-1")], "duplicate edge id"),
    "parent_missing": (lambda: [edge("e2", "junior-1", "senior-1", "nope")], "missing or does not precede"),
    "parent_later": (lambda: [edge("e2", "junior-1", "senior-1", "e1"), edge("e1", "planner-1", "junior-1")], "missing or does not precede"),
    "issuer_not_parent_child": (lambda: [edge("e1", "planner-1", "junior-1"), edge("e2", "senior-1", "admin-1", "e1")], "not the child"),
    "self_cycle": (lambda: [edge("e1", "planner-1", "planner-1")], "cycle"),
    "cycle_back_to_root": (lambda: [edge("e1", "planner-1", "junior-1"), edge("e2", "junior-1", "planner-1", "e1")], "cycle"),
    "cycle_mid_path": (lambda: [edge("e1", "planner-1", "junior-1"), edge("e2", "junior-1", "senior-1", "e1"),
                                edge("e3", "senior-1", "junior-1", "e2")], "cycle"),
    "static_delegate": (lambda: [edge("e1", "planner-1", "agent-1")], "static delegate"),
    "static_delegate_issuer": (lambda: [edge("e1", "agent-1", "planner-1")], "static delegate"),
    "unknown_principal": (lambda: [edge("e1", "planner-1", "ghost")], "unknown principal"),
    "depth": (lambda: ok_chain() + [edge("e4", "senior-1", "admin-1", "e3", sc(["transfer_inventory"], ("Part", ["P1"])), 4),
                                    edge("e5", "admin-1", "nobody-1", "e4", sc(["transfer_inventory"], ("Part", ["P1"])), 3)], "depth"),
    "scope_ops_amplification": (lambda: [edge("e1", "planner-1", "junior-1", scope=sc(["transfer_inventory"], ("Part", None))),
                                         edge("e2", "junior-1", "senior-1", "e1", sc(["transfer_inventory", "expedite_purchase_order"], ("Part", None)))], "scope amplification"),
    "scope_keys_amplification": (lambda: [edge("e1", "planner-1", "junior-1", scope=sc(["transfer_inventory"], ("Part", ["P1"]))),
                                          edge("e2", "junior-1", "senior-1", "e1", sc(["transfer_inventory"], ("Part", ["P1", "P2"])))], "scope amplification"),
    "scope_null_keys_amplification": (lambda: [edge("e1", "planner-1", "junior-1", scope=sc(["transfer_inventory"], ("Part", ["P1"]))),
                                               edge("e2", "junior-1", "senior-1", "e1", sc(["transfer_inventory"], ("Part", None)))], "scope amplification"),
    "scope_type_amplification": (lambda: [edge("e1", "planner-1", "junior-1", scope=sc(["transfer_inventory"], ("Part", None))),
                                          edge("e2", "junior-1", "senior-1", "e1", sc(["transfer_inventory"], ("Lot", None)))], "scope amplification"),
    "expiry_later": (lambda: [edge("e1", "planner-1", "junior-1", exp=5), edge("e2", "junior-1", "senior-1", "e1", exp=6)], "expiry amplification"),
    "expiry_null_under_finite": (lambda: [edge("e1", "planner-1", "junior-1", exp=5), edge("e2", "junior-1", "senior-1", "e1", exp=None)], "expiry amplification"),
    "op_not_in_ops_spec": (lambda: [edge("e1", "planner-1", "junior-1", scope=sc(["op_zzz"], ("Part", None)))], "not in the ops spec"),
}


@pytest.mark.parametrize("name", sorted(REJECT))
def test_validate_strict_rejects(base, name):
    build, msg = REJECT[name]
    with pytest.raises(ValueError, match=msg):
        validate_strict(v2(base, *build()), OPS)


def test_dangling_revoked_and_schema_and_depth_bounds(base):
    with pytest.raises(ValueError, match="revoked edge"):
        validate_strict(v2(base, edge("e1", "planner-1", "junior-1"), revoked=["zz"]), OPS)
    validate_strict(v2(base, edge("e1", "planner-1", "junior-1"), revoked=["e1"]), OPS)
    for bad in (0, 17):
        with pytest.raises(ValueError, match="schema"):
            validate_strict({**base, "max_delegation_depth": bad})
    e = edge("e1", "planner-1", "junior-1")
    e["surprise"] = 1  # additionalProperties false
    with pytest.raises(ValueError, match="schema"):
        validate_strict(v2(base, e))
    with pytest.raises(ValueError, match="schema"):
        validate_strict({k: v for k, v in base.items() if k != "revoked"})
    for k in ("scope", "parent", "expires_at"):  # every edge key required
        e = edge("e1", "planner-1", "junior-1")
        del e[k]
        with pytest.raises(ValueError, match="schema"):
            validate_strict(v2(base, e))


def test_scope_helpers():
    s = sc(["transfer_inventory"], ("Part", ["P1", "P2"]), ("Lot", None))
    assert scope_covers(s, "transfer_inventory", [("Part", "P1"), ("Lot", "L9")])
    assert not scope_covers(s, "transfer_inventory", [("Part", "P3")])        # key outside
    assert not scope_covers(s, "expedite_purchase_order", [("Part", "P1")])        # op outside
    assert not scope_covers(s, "transfer_inventory", [("Part", "P1"), ("Bin", "B")])  # type outside: EVERY resource must match
    assert scope_covers(s, "transfer_inventory", [])                           # no resources: op membership only
    assert not scope_covers(s, "expedite_purchase_order", [])
    assert scope_subset(sc(["transfer_inventory"], ("Part", ["P1"])), s) and not scope_subset(sc(["transfer_inventory"], ("Part", ["P9"])), s)
    assert scope_subset(sc([]), s) and scope_subset(s, s)


def test_edge_path_and_digest(base):
    spec = v2(base, *ok_chain())
    assert [e["id"] for e in edge_path(spec, "e3")] == ["e1", "e2", "e3"]
    with pytest.raises(KeyError):
        edge_path(spec, "zz")
    cyc = v2(base, edge("a", "planner-1", "junior-1", "b"), edge("b", "junior-1", "senior-1", "a"))
    with pytest.raises(ValueError):
        edge_path(cyc, "a")
    d1 = authority_digest(v2(base, *ok_chain(), revoked=["e2", "e1"]))
    assert d1 == authority_digest(v2(base, *ok_chain(), revoked=["e1", "e2"]))  # revoked sorted
    swapped = ok_chain()
    swapped[0], swapped[1] = swapped[1], swapped[0]
    assert d1 != authority_digest(v2(base, *swapped, revoked=["e1", "e2"]))     # issuance order matters
    assert authority_digest(load_auth_spec("manufacturing")) == __import__("hashlib").sha256(
        json.dumps(load_auth_spec("manufacturing"), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
