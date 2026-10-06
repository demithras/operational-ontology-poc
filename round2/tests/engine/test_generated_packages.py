"""Property: for generated valid IR packages (eoo_ir.strategies), every action can be driven through the
same pipeline with generated bindings, with zero Engine edits; dispatch happens only via DISPATCH_TABLE."""
import json
import random
from collections import Counter
from pathlib import Path

from hypothesis import given, settings, strategies as st

from eoo_engine import DISPATCH_TABLE, Engine, Journal
from eoo_engine.pipeline import TRANSITIONS
from eoo_h15.isolation import isolated_constants
from eoo_ir import validate
from eoo_ir.strategies import valid_packages
from genbind import bind_all, conflicting_policy_refs, inputs_for, permissive_variant, principals, seed

ROOT = Path(__file__).resolve().parents[2]
REACHABLE = {"DENIED", "PENDING_APPROVAL", "RECONCILED_SUCCESS", "RECONCILED_FAILED", "OUTCOME_UNKNOWN"}
STATS: Counter = Counter()


def drive(pkg: dict, mode: str, rnd_seed: int):
    model, b, reg, ad = bind_all(pkg, mode, random.Random(rnd_seed))
    eng = Engine(pkg, b, reg, clock=_clock())
    seed(eng, model)
    for p in principals(model, eng):
        eng.register_principal(p)
    out = []
    for aid, spec in sorted(model.all("actions").items()):
        before = eng.state().state_hash()
        n_eff = len(eng.effect_log)
        inputs = inputs_for(spec, eng.read_view(), model)
        rec = eng.propose(aid, inputs if inputs is not None else {}, "tester", idempotency_key=f"k-{aid}")
        if rec["state"] == "PENDING_APPROVAL":
            try:
                rec = eng.approve(rec["exec"], "second")
            except Exception:
                pass
        out.append((spec, rec, before, n_eff, inputs))
    return model, eng, out


def _clock():
    n = iter(range(10 ** 9))
    return lambda: f"c{next(n)}"


def check_invariants(model, eng, out):
    for spec, rec, before, n_eff, _ in out:
        st_ = rec["state"]
        assert st_ in REACHABLE, (spec.rid, st_)
        prev = None
        for s in rec["history"]:
            assert s in TRANSITIONS[prev] or s == prev, (prev, s)
            prev = s
        mine = eng.effect_log.where(execution=rec["exec"])
        committed = "EFFECTS_COMMITTED" in rec["history"]
        assert len(mine) == (len(spec.effects) if committed else 0), (spec.rid, rec["history"], len(mine))
        if st_ in ("DENIED", "PENDING_APPROVAL"):
            assert not committed
        assert eng.provenance.where(exec=rec["exec"])
        STATS[st_] += 1
        if committed:
            STATS.update(f"op:{e.operation}" for e in spec.effects)
    copy = Journal()
    copy.records = [dict(r) for r in eng.journal]
    again = Engine({**_PKG[0]}, eng.bindings, eng.adapters, journal=copy)
    assert again.fingerprint() == eng.fingerprint()


_PKG: list = [None]


@given(pkg=valid_packages(), rnd_seed=st.integers(0, 2 ** 16), widen=st.sampled_from([True, True, True, False]))
def _prop_random(pkg, rnd_seed, widen):
    pkg = permissive_variant(pkg) if widen else pkg  # widen: authority can pass, so later gates get exercised
    _PKG[0] = pkg
    model, eng, out = drive(pkg, "random", rnd_seed)
    check_invariants(model, eng, out)


# derandomized: the success count asserted below is a property of the example set, which must not vary run to run
@settings(derandomize=True)
@given(pkg=valid_packages())
def _prop_permissive(pkg):
    pkg = permissive_variant(pkg)
    assert validate(pkg) == []
    _PKG[0] = pkg
    model, eng, out = drive(pkg, "permissive", 0)
    check_invariants(model, eng, out)
    for spec, rec, before, n_eff, inputs in out:
        if rec["state"] == "DENIED":
            g = rec["gates"][-1]
            allowed = {"inputs", "effects", "integrity"}
            if g["gate"] == "authority":
                assert g["detail"]["deny"], g  # only a generated deny rule may override the universal allow
            elif g["gate"] == "policy":
                assert conflicting_policy_refs(model), g
            else:
                assert g["gate"] in allowed, (spec.rid, g)
            STATS[f"permissive_denied:{g['gate']}"] += 1
        else:
            assert rec["state"] == "RECONCILED_SUCCESS", (spec.rid, rec["state"], rec["gates"])
            STATS["permissive_success"] += 1


def test_generated_packages_random_bindings():
    STATS.clear()
    with isolated_constants():
        _prop_random()
    print(dict(STATS))
    # invariants are asserted per example in check_invariants; this only guards against a vacuous run
    reached = [s_ for s_ in ("PENDING_APPROVAL", "RECONCILED_SUCCESS", "RECONCILED_FAILED", "OUTCOME_UNKNOWN")
               if STATS[s_]]
    assert STATS["DENIED"] and len(reached) >= 2, STATS


def test_generated_packages_permissive_bindings_reach_success():
    STATS.clear()
    with isolated_constants():
        _prop_permissive()
    print(dict(STATS))
    assert STATS["permissive_success"] > 50, STATS
    store_ops = sum(STATS[f"op:{o}"] for o in ("create", "update", "delete", "link", "unlink"))
    adapter_ops = sum(STATS[f"op:{o}"] for o in ("external_call", "git_change"))
    assert store_ops > 0 and adapter_ops > 0, STATS  # both effect routes were committed in this run


def test_dispatch_only_via_dispatch_table(monkeypatch):
    calls: Counter = Counter()

    class Spy:
        def __init__(self, kind, inner):
            self.kind, self.inner = kind, inner
            self.ops = {op: self._wrap(op, fn) for op, fn in inner.ops.items()}

        def _wrap(self, op, fn):
            def w(*a, **k):
                calls[f"{self.kind}.{op}"] += 1
                return fn(*a, **k)
            return w

        def compile(self, r, model):
            calls[f"{self.kind}.compile"] += 1
            return self.inner.compile(r, model)

    for kind, h in list(DISPATCH_TABLE.items()):
        monkeypatch.setitem(DISPATCH_TABLE, kind, Spy(kind, h))
    pkg = json.loads((ROOT / "tests" / "h15" / "openpona_coverage_ir.json").read_text())
    pkg = permissive_variant(pkg)
    model, eng, out = drive(pkg, "permissive", 0)
    for kind in DISPATCH_TABLE:
        assert calls[f"{kind}.compile"] == 2 * len(pkg[kind]), kind  # two loads: genbind's model + the Engine
    assert calls["actions.propose"] == len(pkg["actions"])
    assert calls["authority_rules.decide"] >= len(pkg["actions"])
    assert calls["policies.evaluate"] > 0 and calls["constraints.evaluate"] > 0
    monkeypatch.delitem(DISPATCH_TABLE, "constraints")  # no hidden path: without the handler nothing loads
    import pytest
    from eoo_engine import LoadError
    with pytest.raises(LoadError):
        Engine(pkg, eng.bindings, eng.adapters)
