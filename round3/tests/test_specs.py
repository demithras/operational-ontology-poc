import copy
import json
from pathlib import Path

import jsonschema
import pytest

from r3_shared.authspec import allowed_operations, load_auth_spec, validate_auth_spec
from r3_shared.opsspec import Unevaluable, World, evaluate, load_ops_spec, validate_ops_spec

ROOT = Path(__file__).resolve().parents[1]
R2 = ROOT.parent / "round2" / "domains"
IRS = {"manufacturing": R2 / "manufacturing" / "ir.json", "project": R2 / "project" / "ir.v3.json"}
DOMAINS = list(IRS)
FORBIDDEN = ("gate pass", "gate_pass", "minter", "package_id", "WriteGrant", "LogicBinding", "implementation_ref", "rego:", "authority_refs")


@pytest.mark.parametrize("d", DOMAINS)
def test_every_ir_action_and_function_appears_exactly_once(d):
    ir, spec = json.loads(IRS[d].read_text()), load_ops_spec(d)
    acts = [o["name"] for o in spec["operations"]] + [u["name"] for u in spec["unsupported"] if u["kind"] == "action"]
    fns = [r["name"] for r in spec["reads"]] + [u["name"] for u in spec["unsupported"] if u["kind"] == "function"]
    assert sorted(acts) == sorted(a["id"] for a in ir["actions"])
    assert sorted(fns) == sorted(f["id"] for f in ir["functions"])
    assert len(set(acts)) == len(acts) and len(set(fns)) == len(fns)
    assert all(u["reason"].strip() for u in spec["unsupported"])


@pytest.mark.parametrize("d", DOMAINS)
def test_constraints_accounted_for(d):
    ir, spec = json.loads(IRS[d].read_text()), load_ops_spec(d)
    covered = {i["ir"] for i in spec["invariants"]} | {e["ir"] for e in spec["excluded_constraints"]}
    assert covered == {c["id"] for c in ir["constraints"]}


@pytest.mark.parametrize("d", DOMAINS)
def test_spec_is_architecture_neutral(d):
    text = (ROOT / "spec" / "ops" / f"{d}.json").read_text()
    assert not [w for w in FORBIDDEN if w in text]


@pytest.mark.parametrize("d", DOMAINS)
def test_schema_rejects_known_negatives(d):
    spec = load_ops_spec(d)
    bad = copy.deepcopy(spec)
    del bad["operations"][0]["effects"]
    with pytest.raises(jsonschema.ValidationError):
        validate_ops_spec(bad)
    bad = copy.deepcopy(spec)
    bad["operations"][0]["gated_inputs"].append("no_such_input")
    with pytest.raises(ValueError):
        validate_ops_spec(bad)
    bad = copy.deepcopy(spec)
    bad["domain"] = "nope"
    with pytest.raises(jsonschema.ValidationError):
        validate_ops_spec(bad)


@pytest.mark.parametrize("d", DOMAINS)
def test_seed_is_closed_and_typed(d):
    spec = load_ops_spec(d)
    types = {t["name"]: {f["name"] for f in t["fields"]} for t in spec["resource_types"]}
    refs = set()
    for o in spec["seed"]["objects"]:
        assert o["type"] in types, o
        assert set(o["props"]) <= types[o["type"]], (o["type"], set(o["props"]) - types[o["type"]])
        refs.add(f"{o['type']}:{o['key']}")
    assert len(refs) == len(spec["seed"]["objects"])
    lt = {l["name"]: l for l in spec["link_types"]}
    for l in spec["seed"]["links"]:
        assert l["src"] in refs and l["dst"] in refs, l
        assert l["src"].split(":")[0] in lt[l["link_type"]]["from_types"] and l["dst"].split(":")[0] in lt[l["link_type"]]["to_types"], l


def test_manufacturing_preconditions_evaluate_on_seed():
    spec = load_ops_spec("manufacturing")
    op = next(o for o in spec["operations"] if o["name"] == "transfer_inventory")
    w = World.from_seed(spec["seed"], now=0)
    ok = {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": "PX-17", "quantity": 60}
    res = {p["id"]: evaluate(p["predicate"], op, ok, w) for p in op["preconditions"]}
    assert res == {"quantity-positive-int": True, "endpoints-differ": True, "source-has-stock": True}
    # known negatives: each precondition flips on its own bad input
    for bad, which in (({"quantity": 0}, "quantity-positive-int"), ({"quantity": True}, "quantity-positive-int"),
                       ({"destination_warehouse": "WH-B"}, "endpoints-differ"), ({"quantity": 141}, "source-has-stock"),
                       ({"part": "PX-NOPE"}, "source-has-stock")):
        r = {p["id"]: evaluate(p["predicate"], op, {**ok, **bad}, w) for p in op["preconditions"]}
        assert r[which] is False and sum(1 for v in r.values() if v is False) >= 1, (bad, r)
    # business rules: freshness at now=0 passes, at now=6 fails (stale)
    rules = {r["id"]: r for r in op["business_rules"]}
    stale = rules["transfer-stale-evidence"]["when"]
    assert evaluate(stale, op, ok, World.from_seed(spec["seed"], now=5)) is False
    assert evaluate(stale, op, ok, World.from_seed(spec["seed"], now=6)) is True
    assert evaluate(rules["transfer-large-needs-approval"]["when"], op, {**ok, "quantity": 81}, w) is True
    assert evaluate(rules["transfer-large-needs-approval"]["when"], op, ok, w) is False
    assert evaluate(rules["transfer-quarantine"]["when"], op, {**ok, "part": "PX-900", "source_warehouse": "WH-A",
                                                              "destination_warehouse": "WH-B"}, w) is True
    with pytest.raises(Unevaluable):
        evaluate(rules["transfer-protected-route"]["when"], op, ok, w)


def test_project_simple_preconditions_on_seed():
    spec = load_ops_spec("project")
    w = World.from_seed(spec["seed"])
    op = next(o for o in spec["operations"] if o["name"] == "start_run")
    pre = {p["id"]: p["predicate"] for p in op["preconditions"]}
    assert evaluate(pre["phase-preregistered"], op, {"hypothesis": "H-B"}, w) is True
    assert evaluate(pre["phase-preregistered"], op, {"hypothesis": "H-A"}, w) is False
    assert evaluate(pre["has-freeze-hash"], op, {"hypothesis": "H-A"}, w) is False


@pytest.mark.parametrize("d", DOMAINS)
def test_authority_fixture(d):
    a, ops = load_auth_spec(d), load_ops_spec(d)
    opnames = [o["name"] for o in ops["operations"]]
    people = [p for p in a["principals"]]
    assert len(people) >= 6
    agents = [p for p in people if p["kind"] == "agent"]
    assert len(agents) >= 2 and any(p.get("hostile") for p in agents)
    admin = allowed_operations(a, "admin-1", opnames)
    assert admin == set(opnames)
    nonempty = [p for p in agents if 0 < len(allowed_operations(a, p["id"], opnames)) < len(admin)
                and allowed_operations(a, p["id"], opnames) < admin]
    assert len(nonempty) >= 2
    assert any(p.get("hostile") for p in nonempty)
    assert allowed_operations(a, "viewer-1", opnames) == set() if d == "project" else True
    assert all(s["operation_grants"] == [] for s in a["service_accounts"])
    assert any(g["effect"] == "deny" and g["operation"] == "write:canonical-state" for g in a["grants"])
    # every grant names a real operation, approval name, wildcard or write capability
    for g in a["grants"]:
        assert g["operation"] == "*" or g["operation"] in opnames or g["operation"].split(":")[0] in (
            "approval", "write", "update", "mitigate_high_priority") or g["operation"] == "mitigate_high_priority", g


def test_authority_delegation_semantics_known_negatives():
    a = load_auth_spec("manufacturing")
    ops = ["transfer_inventory", "expedite_purchase_order"]
    assert allowed_operations(a, "agent-1", ops) == {"transfer_inventory"}  # delegable grant + planner delegator
    assert allowed_operations(a, "agent-orphan", ops) == set()  # delegator holds nothing
    assert allowed_operations(a, "junior-1", ops) == {"transfer_inventory"}
    b = copy.deepcopy(a)
    for g in b["grants"]:
        if g["id"] == "transfer-inventory-agent-grant":
            g["delegable"] = False
    assert allowed_operations(b, "agent-1", ops) == set()  # non-delegable grant gives a delegated agent nothing
    c = copy.deepcopy(a)
    c["grants"].append({"id": "deny-agent", "effect": "deny", "principal": {"id": "planner-1"}, "resource": {"any": True},
                        "operation": "transfer_inventory", "delegable": False, "origin": "neutral-extension"})
    assert allowed_operations(c, "agent-1", ops) == set()  # deny on a principal in the chain applies
    with pytest.raises(jsonschema.ValidationError):
        d = copy.deepcopy(a)
        d["principals"] = d["principals"][:3]
        validate_auth_spec(d)


def test_regeneration_is_byte_identical():
    import subprocess, sys
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_ops_spec.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_delegate_semantics_static_bound():
    from r3_shared.authspec import allowed_operations, load_auth_spec
    from r3_shared.opsspec import load_ops_spec
    spec, ops = load_auth_spec("manufacturing"), [o["name"] for o in load_ops_spec("manufacturing")["operations"]]
    assert allowed_operations(spec, "agent-orphan", ops) == set()
    assert "transfer_inventory" in allowed_operations(spec, "agent-1", ops)
    # agent-hostile-1 is limited to WH-B/WH-C resources: a per-request resource binding, out of scope for this static bound
    assert "transfer_inventory" in allowed_operations(spec, "agent-hostile-1", ops)
