"""P1g-5 / P1g-8 forms: validate_recovery_view exact keys/order/vocabulary, validate_reply forms, DENIED may not name a dependency;
dependency graph: generated == committed, every op of both domains exactly once, schema known-negatives."""
import copy
import json
from pathlib import Path

import jsonschema
import pytest

from r3_shared import recovery
from r3_shared.recovery import (DEP_UNAVAILABLE, IN_DOUBT, INPUT_INVALID_REASONS, RECOVERY_VIEW_KEYS, STATE_LOST, RecoveryFormError,
                                validate_recovery_view, validate_reply, view_bytes)

ROUND3 = Path(__file__).resolve().parents[1]
H = "a" * 64


def view():
    return {"form": "r3-recovery-1",
            "committed": [{"request_id": "r1", "world_seq": 3, "authority_version": H}, {"request_id": None, "world_seq": 9, "authority_version": H}],
            "intents": [{"request_id": "r1", "effect_index": 0, "system": "ERP", "chain_ids": 1, "state": "PENDING", "confidence": "full"},
                        {"request_id": "r1", "effect_index": 1, "system": "WMS", "chain_ids": 1, "state": "UNKNOWN", "confidence": "low"}],
            "authority": {"version": H, "lease_until": 7}, "approvals_open": ["0" * 64, "f" * 64]}


def test_valid_view_and_canonical_bytes():
    v = view()
    assert validate_recovery_view(v) is v and RECOVERY_VIEW_KEYS == ("form", "committed", "intents", "authority", "approvals_open")
    assert view_bytes(v) == view_bytes(json.loads(json.dumps(v, sort_keys=False))) and b" " not in view_bytes(v)
    assert validate_recovery_view({**view(), "authority": {"version": None, "lease_until": None}, "committed": [], "intents": [], "approvals_open": []})


def mutations():
    def m(f):
        v = view(); f(v); return v
    yield "extra top key", m(lambda v: v.update(extra=1))
    yield "missing key", m(lambda v: v.pop("approvals_open"))
    yield "wrong form", m(lambda v: v.update(form="r3-recovery-2"))
    yield "committed unsorted", m(lambda v: v["committed"].reverse())
    yield "duplicate world_seq", m(lambda v: v["committed"][1].update(world_seq=3))
    yield "duplicate request_id", m(lambda v: v["committed"][1].update(request_id="r1", world_seq=10))
    yield "committed extra key", m(lambda v: v["committed"][0].update(x=1))
    yield "bad authority hex", m(lambda v: v["committed"][0].update(authority_version="XYZ"))
    yield "bool world_seq", m(lambda v: v["committed"][0].update(world_seq=True))
    yield "intents unsorted", m(lambda v: v["intents"].reverse())
    yield "intent bad state", m(lambda v: v["intents"][0].update(state="DONE"))
    yield "intent bad confidence", m(lambda v: v["intents"][0].update(confidence="high"))
    yield "intent missing chain_ids", m(lambda v: v["intents"][0].pop("chain_ids"))
    yield "bool chain_ids", m(lambda v: v["intents"][0].update(chain_ids=True))
    yield "authority extra", m(lambda v: v["authority"].update(extra=1))
    yield "lease_until bool", m(lambda v: v["authority"].update(lease_until=True))
    yield "approvals unsorted", m(lambda v: v["approvals_open"].reverse())
    yield "approvals not sha", m(lambda v: v["approvals_open"].append("short"))
    yield "approvals duplicate", m(lambda v: v.update(approvals_open=["0" * 64, "0" * 64]))


@pytest.mark.parametrize("name,bad", list(mutations()), ids=[n for n, _ in mutations()])
def test_view_known_negatives(name, bad):
    with pytest.raises(RecoveryFormError):
        validate_recovery_view(bad)
    assert issubclass(RecoveryFormError, ValueError)


def test_view_not_an_object():
    for bad in ([], None, "x"):
        with pytest.raises(RecoveryFormError):
            validate_recovery_view(bad)


def test_reply_vocabulary():
    assert (DEP_UNAVAILABLE, IN_DOUBT, STATE_LOST, recovery.CRASHED) == ("dependency_unavailable", "in_doubt", "state_lost", "crashed")
    assert INPUT_INVALID_REASONS == ("schema_invalid", "unknown_operation", "unknown_tool", "bad_args")
    validate_reply("UNAVAILABLE", {"reason": DEP_UNAVAILABLE, "dependency": "AUTH"})
    validate_reply("UNAVAILABLE", {"reason": DEP_UNAVAILABLE, "dependency": "EXT:ERP"})
    validate_reply("UNKNOWN", {"reason": IN_DOUBT})
    validate_reply("UNAVAILABLE", {"reason": STATE_LOST})
    validate_reply("UNKNOWN", {"reason": "crashed"})
    validate_reply("DENIED", {"reason": "not_authorized"})
    for status, body in (("UNAVAILABLE", {"reason": DEP_UNAVAILABLE}), ("UNAVAILABLE", {"reason": DEP_UNAVAILABLE, "dependency": ""}),
                         ("UNAVAILABLE", {"reason": DEP_UNAVAILABLE, "dependency": "AUTH", "x": 1}), ("UNKNOWN", {"reason": IN_DOUBT, "dependency": "AUTH"}),
                         ("UNAVAILABLE", {"reason": STATE_LOST, "dependency": "AUTH"}), ("UNKNOWN", {"reason": DEP_UNAVAILABLE, "dependency": "AUTH"}),
                         ("UNKNOWN", {"reason": "weird"}), ("OK", {}), ("INVALID", {"reason": "schema_invalid"}), ("UNAVAILABLE", []),
                         ("UNKNOWN", {"reason": "crashed", "x": 1})):
        with pytest.raises(RecoveryFormError):
            validate_reply(status, body)


def test_denied_never_names_a_dependency():
    for body in ({"reason": "not_authorized", "dependency": "AUTH"}, {"reason": DEP_UNAVAILABLE}, {"reason": IN_DOUBT}, {"reason": "crashed"},
                 {"reason": STATE_LOST}, {"dependency": "ANCHOR"}):
        with pytest.raises(RecoveryFormError):
            validate_reply("DENIED", body)


# ---- dependency graph -------------------------------------------------------------------------------------------------
def load_graph():
    return json.loads((ROUND3 / "spec" / "gate5" / "dependency-graph.json").read_text())


def test_generated_equals_committed(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("gen_depgraph", ROUND3 / "scripts" / "gen_depgraph.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert (ROUND3 / "spec" / "gate5" / "dependency-graph.json").read_text() == mod.render(mod.build())
    assert mod.main(["--check"]) == 0
    stale = copy.deepcopy(load_graph())
    stale["operations"]["manufacturing"]["transfer_inventory"]["outcome"] = []
    assert mod.render(stale) != (ROUND3 / "spec" / "gate5" / "dependency-graph.json").read_text()      # known negative for the comparison


def test_every_op_of_both_domains_exactly_once_set_difference():
    g = load_graph()
    for dom, fname in (("manufacturing", "manufacturing.json"), ("project", "project.h28.json")):
        ops = [o["name"] for o in json.loads((ROUND3 / "spec" / "ops" / fname).read_text())["operations"]]
        assert len(ops) == len(set(ops))
        assert set(ops) - set(g["operations"][dom]) == set() and set(g["operations"][dom]) - set(ops) == set()
    base = [o["name"] for o in json.loads((ROUND3 / "spec" / "ops" / "project.json").read_text())["operations"]]
    assert set(base) <= set(g["operations"]["project"]) and {"publish_result", "notify_reviewer"} <= set(g["operations"]["project"])
    assert set(g["operations"]["*"]) == {"approve", "delegate", "revoke"}


def test_graph_content_matches_the_frozen_text():
    g = load_graph()
    assert g["surfaces"] == {"governed_mutation": {"decision": ["AUTH", "ANCHOR"]}, "read": {"decision": ["AUTH"]},
                             "replay": {"decision": ["ANCHOR"]}, "explain": {"decision": ["ANCHOR"]}, "reconcile": {"outcome": ["OBS"]}}
    m, p = g["operations"]["manufacturing"], g["operations"]["project"]
    assert m["transfer_inventory"]["outcome"] == ["EXT:WMS", "OBS"] and m["expedite_purchase_order"]["outcome"] == ["EXT:ERP", "OBS"]
    assert m["reschedule_work_order"]["outcome"] == ["EXT:MES", "OBS"]
    assert p["publish_result"]["outcome"] == ["EXT:REGISTRY", "OBS"] and p["notify_reviewer"]["outcome"] == ["EXT:NOTIFY", "OBS"]
    assert all(v["outcome"] == [] for k, v in p.items() if k not in ("publish_result", "notify_reviewer"))
    assert g["systems"]["manufacturing"]["GEN-NULL"] == ["EXT:GEN-NULL"] and g["systems"]["project"]["GEN-NULL"] == ["EXT:GEN-NULL"]  # no OBS


def test_graph_schema_known_negatives():
    schema = json.loads((ROUND3 / "schemas" / "dependency-graph.schema.json").read_text())
    jsonschema.validate(load_graph(), schema)
    def mut(f):
        g = copy.deepcopy(load_graph()); f(g); return g
    for bad in (mut(lambda g: g.update(extra=1)), mut(lambda g: g.update(version="r3-depgraph-2")),
                mut(lambda g: g["surfaces"]["read"].update(decision=["AUTH", "ANCHOR"])),
                mut(lambda g: g["operations"]["manufacturing"]["transfer_inventory"].update(outcome=["WMS"])),
                mut(lambda g: g["operations"]["manufacturing"]["transfer_inventory"].update(surface="read")),
                mut(lambda g: g["operations"]["*"].pop("revoke")),
                mut(lambda g: g["operations"]["manufacturing"]["transfer_inventory"].update(outcome=["EXT:WMS", "EXT:WMS"])),
                mut(lambda g: g.pop("systems"))):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad, schema)


def test_envelope_ops_constants_and_classes():
    e = json.loads((ROUND3 / "spec" / "gate5" / "envelope-ops.json").read_text())
    assert e["version"] == "r3-envelope-ops-1" and e["envelope"]["version"] == "r3-draft-1"
    assert e["constants"] == {"LEASE": 4, "PARTITION_MAX": 12, "LAG_MAX": 3, "WINDOW": 8, "REDELIVERY_MAX": 3, "CRASHES_PER_SEQUENCE_MAX": 3}
    assert sorted(e["classes"]) == [f"F{i}" for i in range(1, 9)] and e["crash_points"] == list(__import__("r3_shared.faultplane", fromlist=["x"]).CRASH_POINTS)
    assert e["composition"]["max_concurrent_classes"] == 2 and ["AUTH", "ANCHOR", "OBS"] in e["composition"]["forbidden_node_sets"]
    assert e["external_world_refusal_order"]["check_order_first"] == "unavailable"
    env = json.loads((ROUND3 / "threat_model" / "survivability_envelope.json").read_text())
    assert env["version"] == "r3-draft-1"
