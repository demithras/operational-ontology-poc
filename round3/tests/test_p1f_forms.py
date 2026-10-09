"""P1f-3 / P1f-7 forms: systems declarations, ExternalRequest/AdapterReply/WriteReceipt, digest and target helpers."""
import copy
import json
from pathlib import Path

import jsonschema
import pytest
from r3_shared import extadapter as ea
from r3_shared import extcap
from r3_shared.extsystems import (idempotency, load_systems, observability, placeholders, render_target, validate_systems)

KEY = b"k" * 32


def _req(**kw):
    root = extcap.mint_root(KEY, "n", "ERP", "d")
    cap = extcap.attenuate(root, system="ERP", operation="expedite", target="po:1", payload_digest="d" * 64, correlation="r1#0",
                           max_uses=1, not_after_tick=9)
    base = dict(request_id="r1", effect_index=0, system="ERP", operation="expedite", target="po:1", payload={"po_id": "1"},
                envelope_text="", cap=cap)
    base.update(kw)
    return base


def test_frozen_systems_documents_validate_and_declare_the_ruled_classes():
    m, p = load_systems("manufacturing"), load_systems("project")
    assert m["window"] == 8 and p["window"] == 8
    assert [observability(m, s) for s in ("WMS", "ERP", "MES", "GEN-NULL")] == ["full", "full", "effects_only", "none"]
    assert [observability(p, s) for s in ("REGISTRY", "NOTIFY", "GEN-NULL")] == ["full", "effects_only", "none"]
    assert idempotency(m, "WMS", "transfer") == idempotency(m, "ERP", "expedite") == "at_most_once"
    assert idempotency(m, "MES", "reschedule") == "idempotent_set"
    assert m["systems"]["GEN-NULL"]["generated"] and p["systems"]["GEN-NULL"]["generated"]


def test_systems_known_negatives():
    base = load_systems("manufacturing")
    muts = [lambda d: d.update(version="r3-external-2"), lambda d: d.pop("window"), lambda d: d.update(window=0),
            lambda d: d.update(extra=1), lambda d: d["systems"]["WMS"].update(observability="partial"),
            lambda d: d["systems"]["WMS"]["operations"]["transfer"].update(idempotency="sometimes"),
            lambda d: d["systems"]["WMS"]["operations"]["transfer"].update(semantics="rm_rf"),
            lambda d: d["systems"]["WMS"]["operations"]["transfer"].update(target_rule="a<b"),
            lambda d: d["systems"]["WMS"].update(operations={}), lambda d: d["systems"]["WMS"]["operations"]["transfer"].pop("target_rule"),
            lambda d: d["systems"]["GEN-NULL"].pop("generated"), lambda d: d.update(systems={})]
    for mut in muts:
        bad = copy.deepcopy(base)
        mut(bad)
        with pytest.raises((ValueError, jsonschema.ValidationError)):
            validate_systems(bad)


def test_target_rules_render_deterministically():
    m = load_systems("manufacturing")
    rule = m["systems"]["WMS"]["operations"]["transfer"]["target_rule"]
    assert placeholders(rule) == ["part", "source", "destination"]
    pay = {"part": "PX-17", "source": "WH-A", "destination": "WH-B", "quantity": 5}
    assert render_target(rule, pay) == "transfer:PX-17@WH-A->WH-B"
    assert render_target(m["systems"]["ERP"]["operations"]["expedite"]["target_rule"], {"po_id": "PO-9"}) == "po:PO-9"
    with pytest.raises(ValueError):
        render_target(rule, {"part": "P"})


def test_payload_digest_is_canonical_json_sha256():
    import hashlib
    assert ea.payload_digest({"b": 1, "a": [1, 2]}) == hashlib.sha256(b'{"a":[1,2],"b":1}').hexdigest()
    assert ea.payload_digest({"a": 1, "b": 2}) == ea.payload_digest({"b": 2, "a": 1})
    assert ea.payload_digest({"a": 1}) != ea.payload_digest({"a": 1.0 + 1e-9}) != ea.payload_digest({"a": "1"})
    assert ea.payload_digest({"é": 1}) == hashlib.sha256('{"é":1}'.encode()).hexdigest()    # ensure_ascii=False, as the anchor canon


def test_correlation_roundtrip_and_negatives():
    assert ea.parse_correlation(ea.correlation("req#a", 3)) == ("req#a", 3)
    for bad in ("", "x", "#1", "r#", "r#x", "r#-1"):
        with pytest.raises(ea.FormError):
            ea.parse_correlation(bad)


def test_external_request_form_and_strict_cap_rules():
    r = ea.ExternalRequest(**_req())
    assert ea.validate_request(r.as_dict()) == r.as_dict()
    root = extcap.mint_root(KEY, "n", "ERP", "d")
    other_cor = extcap.attenuate(root, correlation="r9#0")
    no_cor = extcap.attenuate(root, operation="expedite")
    ea.ExternalRequest(**_req(cap=root))                                     # constructor: shape only ...
    for cap in (root, other_cor, no_cor, "r3cap1.@@@"):                       # ... the strict check refuses these
        with pytest.raises(ea.FormError):
            ea.validate_request(_req(cap=cap))
    for kw in ({"request_id": ""}, {"effect_index": True}, {"effect_index": -1}, {"payload": []}, {"envelope_text": None},
               {"system": ""}, {"cap": "plain"}, {"extra": 1}):
        with pytest.raises((ea.FormError, TypeError)):
            ea.ExternalRequest(**_req(**kw))


def test_reply_and_receipt_forms():
    assert ea.validate_reply({"status": "OK", "body": {"approval": {"x": 1}}})                 # untrusted: any body shape
    for bad in ({"status": "OK"}, {"status": 5, "body": {}}, {"status": "OK", "body": []}, {"status": "OK", "body": {}, "x": 1}):
        with pytest.raises(ea.FormError):
            ea.validate_reply(bad)
    assert ea.validate_receipt({"status": "applied", "reason": "", "seq": 1})
    for bad in ({"status": "ok", "reason": "", "seq": 1}, {"status": "applied", "reason": "", "seq": 0},
                {"status": "applied", "reason": "", "seq": True}, {"status": "applied", "reason": ""}):
        with pytest.raises(ea.FormError):
            ea.validate_receipt(bad)
    assert ea.REPLY_OK == "OK" and set(ea.ADAPTER_IDS) == {"H0", "L1", "L2", "L3", "T1", "T2", "T3", "R1", "R2", "O1", "O2", "G1", "G2", "G3"}


def test_every_new_schema_file_is_valid_json_schema():
    for f in ("external-systems", "external-request", "external-cap", "external-ledger", "external-outcome"):
        s = json.loads((Path(__file__).resolve().parents[1] / "schemas" / f"{f}.schema.json").read_text())
        jsonschema.Draft202012Validator.check_schema(s)
