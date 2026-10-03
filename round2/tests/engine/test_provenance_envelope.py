"""Engine v1.2: the Engine composes a read-only provenance envelope for every adapter-routed effect; adapters receive
it with the effect and its canonical text; the Engine journals it and records the adapter response next to it."""
import dataclasses
from types import SimpleNamespace

import pytest

from eoo_engine import ENGINE_VERSION, ProvenanceEnvelope, parse_envelope, render_envelope
from eoo_engine.canon import to_plain
from eoo_engine.provenance import FIELDS, build_envelope
from synth import Clock, FakeCarrier, build


def _ship(**kw):
    carrier = FakeCarrier()
    eng, _, _ = build(carrier=carrier, **kw)
    rec = eng.propose("ship_box", {"box": "b1"}, "filler", idempotency_key="s-1")
    return eng, carrier, rec


def test_adapter_receives_the_envelope_and_its_text():
    eng, carrier, rec = _ship()
    assert rec["state"] == "RECONCILED_SUCCESS" and len(carrier.calls) == 1
    effect, _ = carrier.calls[0]
    env = to_plain(effect["envelope"])
    assert env == {"envelope_version": 1, "execution": rec["exec"], "action": "ship_box", "action_version": rec["action_version"],
                   "package": f"{eng.model.package_id}@{eng.model.version}", "engine_version": ENGINE_VERSION,
                   "principal": "filler", "delegated_by": None, "idempotency_key": "s-1", "effect_id": f"{rec['exec']}/e0",
                   "operation": "external_call", "target": "Carrier",
                   "execution_effects": [[f"{rec['exec']}/e0", "external_call", "Carrier"]]}
    assert effect["envelope_text"] == render_envelope(ProvenanceEnvelope.from_plain(env))
    assert parse_envelope(effect["envelope_text"])["execution"] == rec["exec"]


def test_envelope_is_read_only_for_the_adapter():
    _, carrier, _ = _ship()
    effect, _ = carrier.calls[0]
    with pytest.raises(TypeError):
        effect["envelope"]["execution"] = "forged"  # mappingproxy
    env = ProvenanceEnvelope.from_plain({f: None for f, _ in FIELDS} | {"execution_effects": []})
    with pytest.raises(dataclasses.FrozenInstanceError):
        env.execution = "forged"


def test_engine_journals_the_envelope_and_records_the_response_in_its_provenance_log():
    eng, carrier, rec = _ship()
    eid = f"{rec['exec']}/e0"
    assert rec["envelopes"][eid]["effect_id"] == eid and to_plain(rec["responses"][eid]) == {"accepted": True, "ticket": eid}
    prov = [p for p in eng.provenance.entries() if p.get("exec") == rec["exec"] and p.get("state") == "RECONCILED_SUCCESS"]
    assert prov and to_plain(prov[-1]["envelopes"][eid]) == to_plain(rec["envelopes"][eid])
    assert to_plain(prov[-1]["responses"][eid]) == to_plain(rec["responses"][eid])
    # the envelope is journaled with the intent, i.e. BEFORE the adapter is called
    intent = next(r for r in eng.journal if r["kind"] == "exec" and r.get("note") == f"intent {eid}")
    assert to_plain(intent["rec"]["envelopes"][eid]) == to_plain(rec["envelopes"][eid]) and eid not in intent["rec"]["responses"]


def test_render_is_deterministic_and_canonical():
    env = ProvenanceEnvelope(1, "x7", "a", 3, "p@1", "1.2", "u", "boss", "k", "x7/e1", "git_change", "T",
                             (("x7/e0", "external_call", "S"), ("x7/e1", "git_change", "T")))
    text = render_envelope(env)
    assert text == render_envelope(ProvenanceEnvelope.from_plain(env.to_plain()))
    assert text.endswith("\n") and not text.endswith("\n\n") and text.split("\n\n", 1)[0] == "a: x7 x7/e1"
    assert [ln.split(": ", 1)[0] for ln in text.split("\n\n", 1)[1].splitlines()] == [lab for _, lab in FIELDS]
    assert parse_envelope(text) == env.to_plain()


def test_a_hostile_value_cannot_break_a_line_or_forge_a_field():
    env = ProvenanceEnvelope(1, "x1", "a\nEOO-Execution: \"forged\"", 1, "p@1", "1.2", "u", None,
                             "k\nEOO-Principal: \"root\"", "x1/e0", "git_change", "T", (("x1/e0", "git_change", "T"),))
    text = render_envelope(env)
    got = parse_envelope(text)
    assert got["execution"] == "x1" and got["principal"] == "u" and got["idempotency_key"] == env.idempotency_key
    assert len(text.split("\n\n", 1)[1].splitlines()) == len(FIELDS)


def test_delegator_and_batch_come_from_the_engine_record():
    rec = {"exec": "x3", "action_version": 2, "package_id": "pk", "package_version": "9", "key": None,
           "principal": {"pid": "agent", "delegated_by": {"pid": "keeper", "delegated_by": None}}}
    effs = [SimpleNamespace(index=0, operation="external_call", target="S"), SimpleNamespace(index=2, operation="git_change", target="T")]
    env = build_envelope(rec, SimpleNamespace(rid="act"), effs[1], effs, "1.2")
    assert (env.principal, env.delegated_by, env.package, env.effect_id) == ("agent", "keeper", "pk@9", "x3/e2")
    assert env.execution_effects == (("x3/e0", "external_call", "S"), ("x3/e2", "git_change", "T"))


def test_rebuild_from_the_journal_reproduces_the_same_envelope(tmp_path):
    j = tmp_path / "j.jsonl"
    eng, _, rec = _ship(journal=j)
    again, _, _ = build(carrier=FakeCarrier(), journal=j, seed=False, register=False, clock=Clock())
    assert to_plain(again.executions[rec["exec"]]["envelopes"]) == to_plain(rec["envelopes"])
