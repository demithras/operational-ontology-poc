"""Synthetic definitions: valid IR, Engine == independent oracle, unchanged Engine, oracle independent of the Engine."""
import pytest
from hypothesis import given, settings

from eoo_exp.util import load_oracle
from eoo_h20 import alias, synth, synth_run
from eoo_ir import validate

O = load_oracle("h20", "synth_oracle")


@settings(max_examples=150)
@given(synth.definitions())
def test_generated_packages_are_valid_ir_over_existing_kinds(d):
    pkg = synth.package(d)
    assert validate(pkg) == []
    from eoo_engine import DISPATCH_TABLE
    assert {k for k, v in pkg.items() if isinstance(v, list)} <= set(DISPATCH_TABLE)


@settings(max_examples=250)
@given(synth.definitions())
def test_engine_agrees_with_the_oracle_on_every_generated_definition(d):
    r = synth_run.run(d)
    assert r["mismatches"] == [], (d, r["mismatches"])


def test_generation_is_seeded_and_reaches_every_effect_and_outcome():
    a, b = synth.generate(4, 300), synth.generate(4, 300)
    assert [synth_run.definition_sha(x) for x in a] == [synth_run.definition_sha(x) for x in b]
    rows = [synth_run.run(d) for d in synth.generate(9, 600)]
    assert {r["effect"] for r in rows} == set(synth.EFFECTS)
    assert {"DENIED", "PENDING_APPROVAL", "RECONCILED_SUCCESS", "RECONCILED_FAILED", "OUTCOME_UNKNOWN"} <= {r["observed_state"] for r in rows}


def test_synthetic_ids_never_collide_with_real_domain_tokens():
    from eoo_h16.audit import collect_tokens
    tokens = collect_tokens()
    assert not {v for d in synth.generate(2, 300) for v in synth.ids(d).values() if v in tokens}


def _known(effect="update", **over):
    d = {"i": 1, "fn": {"kind": "plus", "k": 3},
         "action": {"effect": effect, "idempotency": "required", "precondition": "positive", "policy": "none", "policy_t": 5,
                    "constraint": "hard", "cap": 20, "authority": "role"},
         "scenario": {"principal": "actor", "key": "present", "ref": "good", "n": 7, "approval": "approve", "adapter": "confirm", "retry": True}}
    for k, v in over.items():
        d["scenario"][k] = v
    return d


def test_known_positive_and_known_negative_of_the_comparison():
    assert synth_run.run(_known())["observed_state"] == "RECONCILED_SUCCESS"
    r = synth_run.run(_known(n=21))
    assert r["observed_state"] == "DENIED" and r["mismatches"] == []  # hard cap on the would-be state
    assert synth_run.run(_known(principal="outsider"))["observed_state"] == "DENIED"


def test_a_broken_engine_is_caught_by_the_oracle_comparison(monkeypatch):
    from eoo_engine import authority
    real = authority.evaluate

    def allow_all(*a, **k):
        r = real(*a, **k)
        r.allowed = True
        return r
    monkeypatch.setattr(authority, "evaluate", allow_all)
    r = synth_run.run(_known(principal="outsider"))
    assert r["observed_state"] == "RECONCILED_SUCCESS" and any("state" in m for m in r["mismatches"])


def test_the_oracle_does_not_import_the_engine():
    import ast
    from eoo_exp.util import ROOT
    for f in ("synth_oracle", "lifecycle"):
        names = [a.name for n in ast.walk(ast.parse((ROOT / f"oracles/h20/{f}.py").read_text())) if isinstance(n, ast.Import) for a in n.names]
        names += [n.module for n in ast.walk(ast.parse((ROOT / f"oracles/h20/{f}.py").read_text())) if isinstance(n, ast.ImportFrom)]
        assert not [x for x in names if x and x.startswith(("eoo_", "domains"))], (f, names)


def test_alias_probe_is_quiet_on_the_real_engine_and_loud_on_a_name_keyed_engine(monkeypatch):
    defs = synth.generate(21, 120)
    assert alias.probe(defs)["disagreements"] == 0
    from eoo_engine import gates
    real = gates.evaluate_policies

    def keyed(eng, spec, ctx):
        if eng.model.package_id == "manufacturing-ontology":
            return "APPROVED", gates.gate("policy", True, {})
        return real(eng, spec, ctx)
    monkeypatch.setattr(gates, "evaluate_policies", keyed)
    r = alias.probe(defs)
    assert r["disagreements"] > 0 and r["examples"][0]["modes_differing"] == ["manufacturing"]


def test_alias_modes_use_real_domain_identifiers():
    m = alias.alias_modes()
    assert m["manufacturing"]["pkg"] == "manufacturing-ontology" and m["manufacturing"]["act"] == "transfer_inventory"
    assert m["project"]["pkg"] == "project-ontology" and m["project"]["actor"] != m["project"]["approver"]
