"""H23 R1-R4: identity binding, server-side backstop, least exposure, decision binding. Every refusal asserts ZERO effects."""
import pytest

from conv_helpers import MFG_OPS, SAFE_TRANSFER, VALID, FlipDict, zero_effects
from r3_shared.authspec import allowed_operations
from r3_shared.world import diff

ID_FIELDS = ["principal", "actor", "owner", "requested_by", "subject", "sub", "user", "on_behalf_of"]


# -- R1 identity binding ---------------------------------------------------------------------
@pytest.mark.parametrize("field", ID_FIELDS)
@pytest.mark.parametrize("via", ["call_tool", "direct"])
def test_r1_identity_fields_in_args_never_select_authority(mfg, field, via):
    call = getattr(mfg.dep, via)
    with zero_effects(mfg):  # nobody-1 holds nothing; claiming to be planner-1 in args must not help
        r = call(mfg.token("nobody-1"), "expedite_purchase_order", {**VALID["expedite_purchase_order"], field: "planner-1"})
        assert r.status in ("DENIED", "INVALID")
    with zero_effects(mfg):  # even an authorized subject cannot smuggle an identity field
        r = call(mfg.token("planner-1"), "expedite_purchase_order", {**VALID["expedite_purchase_order"], field: "admin-1"})
        assert r.status in ("DENIED", "INVALID")


def test_r1_acting_subject_is_token_subject(mfg):
    r = mfg.dep.direct(mfg.token("planner-1"), "expedite_purchase_order", VALID["expedite_purchase_order"], request_id="a")
    assert r.status == "OK"
    assert mfg.dep.direct(mfg.token("junior-1"), "expedite_purchase_order", {"po_id": "PO-992", "expedite_fee": 1}).status == "DENIED"


@pytest.mark.parametrize("kind", ["forged", "expired", "wrong_aud", "malformed", "empty"])
@pytest.mark.parametrize("via", ["call_tool", "direct"])
def test_r1_bad_tokens_denied_with_zero_effects(mfg, kind, via):
    good = mfg.token("planner-1")
    tok = {"forged": good[:-4] + ("0000" if not good.endswith("0000") else "1111"),
           "expired": mfg.token("planner-1", ttl=1), "wrong_aud": mfg.token("planner-1", aud="paladin"),
           "malformed": "not-a-token", "empty": ""}[kind]
    if kind == "expired":
        mfg.clock.advance(5)
    with zero_effects(mfg):
        r = getattr(mfg.dep, via)(tok, "transfer_inventory", SAFE_TRANSFER, request_id="x1")
        assert r.status == "DENIED"
    assert mfg.dep.tools(tok) == [] and mfg.dep.read(tok, "get", {"type": "Warehouse", "key": "WH-A"}).status == "DENIED"


def test_r1_forged_subject_in_token_body_is_rejected(mfg):
    import base64
    import json
    good = mfg.token("nobody-1")
    body, sig = good.split(".")
    claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    claims["sub"] = "admin-1"
    forged = base64.urlsafe_b64encode(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode()).decode().rstrip("=") + "." + sig
    with zero_effects(mfg):
        assert mfg.dep.direct(forged, "expedite_purchase_order", VALID["expedite_purchase_order"]).status == "DENIED"


@pytest.mark.parametrize("agent,obo,src,dst,expect", [
    ("agent-1", "planner-1", "WH-B", "WH-A", "OK"),
    ("agent-hostile-1", "planner-1", "WH-B", "WH-C", "OK"),
    ("agent-hostile-1", "planner-1", "WH-B", "WH-A", "DENIED"),   # outside the agent's own grant
    ("agent-1", "junior-1", "WH-B", "WH-A", "DENIED"),            # no delegation entry
    ("agent-1", "admin-1", "WH-B", "WH-A", "DENIED"),             # claiming an arbitrary powerful principal
    ("agent-orphan", "nobody-1", "WH-B", "WH-A", "DENIED"),       # delegator holds nothing
    ("agent-1", "nobody-1", "WH-B", "WH-A", "DENIED"),
    ("agent-1", "no-such-principal", "WH-B", "WH-A", "DENIED"),
])
def test_r1_on_behalf_of_obeys_effective_authority_rule(mfg, agent, obo, src, dst, expect):
    args = {**SAFE_TRANSFER, "source_warehouse": src, "destination_warehouse": dst}
    before = mfg.snap()
    r = mfg.dep.direct(mfg.token(agent), "transfer_inventory", args, on_behalf_of=obo, request_id="obo")
    assert r.status == expect, r
    assert (len(diff(before, mfg.snap())) == 1) == (expect == "OK")


@pytest.mark.parametrize("obo", ["researcher-2", "admin-1", "researcher-1"])
def test_r1_project_domain_never_accepts_on_behalf_of(proj, obo):
    with zero_effects(proj):
        for who in ("agent-evidence-1", "agent-draft-1", "researcher-1"):
            r = proj.dep.direct(proj.token(who), "start_run", {"hypothesis": "H-B"}, on_behalf_of=obo)
            assert r.status == "DENIED"


# -- R2 server-side backstop -------------------------------------------------------------------
PRINCIPALS = {"manufacturing": ["planner-1", "junior-1", "supervisor-1", "senior-1", "nobody-1", "admin-1", "agent-1",
                                "agent-hostile-1", "agent-orphan"],
              "project": ["researcher-1", "viewer-1", "admin-1", "agent-evidence-1", "agent-draft-1"]}
OPS = {"manufacturing": MFG_OPS, "project": [o for o in VALID if o not in MFG_OPS]}


@pytest.mark.parametrize("domain", ["manufacturing", "project"])
def test_r2_direct_matches_call_tool_for_every_principal_and_operation(make, domain):
    for who in PRINCIPALS[domain]:
        for op in OPS[domain]:
            a, b = make(domain), make(domain)  # identical fresh worlds: compare decision AND effects
            a0, b0 = a.snap(), b.snap()
            ra = a.dep.call_tool(a.token(who), op, VALID[op], request_id="q")
            rb = b.dep.direct(b.token(who), op, VALID[op], request_id="q")
            assert ra.status == rb.status, (who, op, ra, rb)
            assert diff(a0, a.snap()) == diff(b0, b.snap()), (who, op)


@pytest.mark.parametrize("domain", ["manufacturing", "project"])
def test_r2_operations_not_shown_are_denied_by_the_backstop_with_zero_effects(mfg, proj, domain):
    rig = mfg if domain == "manufacturing" else proj
    for who in PRINCIPALS[domain]:
        tok = rig.token(who)
        shown = {t.name for t in rig.dep.tools(tok)}
        for op in OPS[domain]:
            if op not in shown:
                with zero_effects(rig):
                    assert rig.dep.direct(tok, op, VALID[op], request_id=f"{who}-{op}").status == "DENIED", (who, op)
                    assert rig.dep.call_tool(tok, op, VALID[op]).status == "DENIED"


def test_r2_unknown_tool_and_operation_names_have_no_effect(mfg):
    with zero_effects(mfg):
        for name in ("drop_database", "write:canonical-state", "approval:large_transfer", "*", "", "transfer_inventory "):
            assert mfg.dep.call_tool(mfg.token("admin-1"), name, {}).status in ("DENIED", "INVALID")
            assert mfg.dep.direct(mfg.token("admin-1"), name, {}).status in ("DENIED", "INVALID")


# -- R3 least exposure -----------------------------------------------------------------------
@pytest.mark.parametrize("domain", ["manufacturing", "project"])
def test_r3_tools_list_only_grantable_operations(make, domain):
    rig = make(domain)
    ops = [o["name"] for o in rig.ops["operations"]]
    for p in rig.auth["principals"]:
        listed = {t.name for t in rig.dep.tools(rig.token(p["id"]))}
        if p["delegated_by"] is None:  # the shared static bound agrees exactly for non-delegated principals
            assert listed == allowed_operations(rig.auth, p["id"], ops), p["id"]
        assert listed <= set(ops)
    assert rig.dep.tools(rig.token("nobody-1" if domain == "manufacturing" else "viewer-1")) == []


def test_r3_tool_schemas_come_from_the_operation_catalog(mfg):
    t = {x.name: x for x in mfg.dep.tools(mfg.token("planner-1"))}["transfer_inventory"]
    assert t.input_schema["additionalProperties"] is False
    assert set(t.input_schema["required"]) == {"source_warehouse", "destination_warehouse", "part", "quantity"}


# -- R4 decision binding -----------------------------------------------------------------------
def test_r4_args_changed_after_authorization_cannot_change_the_commit(mfg):
    good = {**SAFE_TRANSFER, "source_warehouse": "WH-B", "destination_warehouse": "WH-C"}
    flip = FlipDict(good, {"destination_warehouse": "WH-A"})  # agent-hostile-1 holds no grant on WH-A
    r = mfg.dep.direct(mfg.token("agent-hostile-1"), "transfer_inventory", flip, on_behalf_of="planner-1", request_id="f1")
    assert r.status == "OK"
    eff = mfg.snap()["effects"]
    assert len(eff) == 1 and eff[0]["payload"]["destination"] == "WH-C"  # what was authorized, nothing else


def test_r4_caller_mutation_after_return_and_returned_data_are_copies(mfg):
    args = dict(SAFE_TRANSFER)
    r = mfg.dep.direct(mfg.token("planner-1"), "transfer_inventory", args, request_id="c1")
    args["quantity"] = 9999
    r.body["effects"] = 99
    assert mfg.snap()["effects"][0]["payload"]["quantity"] == 10
    t = mfg.token("planner-1")
    a = mfg.dep.read(t, "get", {"type": "Warehouse", "key": "WH-A"})
    a.body["props"]["region"] = "tampered"
    assert mfg.dep.read(t, "get", {"type": "Warehouse", "key": "WH-A"}).body["props"]["region"] == "region-1"
    assert mfg.snap()["objects"]["Warehouse:WH-A"]["props"]["region"] == "region-1"


def test_r4_authority_version_is_bound_to_the_commit(mfg):
    r = mfg.dep.direct(mfg.token("planner-1"), "transfer_inventory", SAFE_TRANSFER, request_id="v1")
    assert r.body["authority_version"] == 1
    assert mfg.dep.set_authority(mfg.auth) is None
    assert len(mfg.dep.authority_version()) == 64
    r2 = mfg.dep.direct(mfg.token("planner-1"), "transfer_inventory", {**SAFE_TRANSFER, "quantity": 5}, request_id="v2")
    assert r2.body["authority_version"] == 2


def test_r4_engine_owns_a_copy_of_the_authority_spec(mfg):
    import copy
    auth = copy.deepcopy(mfg.auth)
    mfg.dep.set_authority(auth)
    auth["grants"].clear()  # caller later empties its dict: the installed policy must not change
    assert mfg.dep.direct(mfg.token("planner-1"), "transfer_inventory", SAFE_TRANSFER, request_id="own").status == "OK"
