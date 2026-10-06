"""The DSL baseline fails closed: typed errors only, never a guess, and exactly the schema's accept set."""
import json
import random
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

from eoo_dsl import DslError, compile as dsl_compile, render
from eoo_dsl.loader import load
from eoo_ir import validate
from eoo_ir.strategies import valid_packages

from dsl_docmut import delete, get, mutate, sites

ROOT = Path(__file__).resolve().parents[2]


def accepted(doc) -> bool:
    return validate(doc) == []


def outcome(doc):
    """(compiled doc | None, DslError | None) for the text form of ``doc``."""
    try:
        return dsl_compile(render(doc)), None
    except DslError as e:
        return None, e


@settings(max_examples=300)
@given(valid_packages(), st.integers(0, 2**31))
def test_dsl_accepts_exactly_what_the_schema_accepts(pkg, seed):
    doc = mutate(pkg, random.Random(seed))
    out, err = outcome(doc)
    if accepted(doc):
        assert err is None, (err, json.dumps(doc)[:1500])
        assert json.dumps(out, sort_keys=True) == json.dumps(doc, sort_keys=True)
    else:
        assert err is not None, ("DSL accepted a schema-invalid document", json.dumps(doc)[:1500])


@settings(max_examples=200)
@given(valid_packages(), st.integers(0, 2**31))
def test_every_deletion_mutant_fails_closed(pkg, seed):
    """for any valid E and deletion mutant M: compile(M) raises, OR compile(M) is exactly what M says."""
    rnd = random.Random(seed)
    ps = sites(pkg)
    for path in rnd.sample(ps, min(len(ps), 25)):
        m = delete(pkg, path)
        out, err = outcome(m)
        if err is None:
            assert json.dumps(out, sort_keys=True) == json.dumps(m, sort_keys=True), path  # nothing invented
            assert accepted(m), path
        else:
            assert not accepted(m), (path, err)  # never rejects something valid


@pytest.mark.parametrize("domain", ["manufacturing", "project"])
def test_deletion_mutants_of_real_domains(domain):
    doc = json.loads((ROOT / "domains" / domain / "ir.json").read_text())
    ps = sites(doc)
    rejected = accepted_n = 0
    for path in random.Random(5).sample(ps, min(len(ps), 400)):
        m = delete(doc, path)
        out, err = outcome(m)
        if err is None:
            assert out == m and accepted(m), path
            accepted_n += 1
        else:
            assert not accepted(m), (path, err)
            rejected += 1
    assert rejected > 0  # known-positive: deleting required fields must have been refused
    print(f"{domain}: {rejected} rejected, {accepted_n} accepted (only optional/list-element deletions)")


@settings(max_examples=300)
@given(valid_packages(), st.integers(0, 2**31))
def test_text_corruption_only_raises_typed_errors(pkg, seed):
    rnd = random.Random(seed)
    text = render(pkg)
    for _ in range(3):
        i = rnd.randrange(len(text) + 1)
        op = rnd.choice(["del", "ins", "swapline"])
        if op == "del":
            text = text[:i] + text[i + rnd.randrange(1, 4):]
        elif op == "ins":
            text = text[:i] + rnd.choice(["&a ", "*a", "!x ", ": ", "- ", "\t", "[", "{", "#", "---\n", "'", '"']) + text[i:]
        else:
            ls = text.split("\n")
            if len(ls) > 1:
                a = rnd.randrange(len(ls))
                b = rnd.randrange(len(ls))
                ls[a], ls[b] = ls[b], ls[a]
            text = "\n".join(ls)
    try:
        out = dsl_compile(text)
    except DslError:
        return
    assert accepted(out)
    assert out == load(text)  # accepted text means exactly what it says


MANU = json.loads((ROOT / "ontology" / "examples" / "manufacturing-minimal.json").read_text())


def _violations(doc) -> int:
    """Deletion mutants whose outcome breaks the fail-closed property (invented or wrongly rejected)."""
    n = 0
    for path in sites(doc):
        m = delete(doc, path)
        try:
            out, err = outcome(m)
        except Exception:  # a crash (non-DslError) is not fail-closed either
            n += 1
            continue
        if err is None:
            n += int(json.dumps(out, sort_keys=True) != json.dumps(m, sort_keys=True) or not accepted(m))
        else:
            n += int(accepted(m))
    return n


def test_property_has_teeth_against_defective_compilers(monkeypatch):
    import eoo_dsl.compiler as comp
    from eoo_dsl import spec

    assert _violations(MANU) == 0  # the real compiler is clean on this package

    real = comp.check

    def defaulting(doc, sp, path):  # DEFECT: invents required=false / version for missing fields, then validates
        for o in doc.get("object_types", []):
            for p in o.get("properties", []):
                p.setdefault("required", False)
        for a in doc.get("actions", []):
            a.setdefault("version", "v0")
        real(doc, sp, path)

    monkeypatch.setattr(comp, "check", defaulting)
    assert _violations(MANU) > 0, "the fail-closed property did not notice a compiler that invents semantics"
    monkeypatch.setattr(comp, "check", lambda doc, sp, path: None)  # DEFECT: no typing at all
    assert _violations(MANU) > 0
    assert spec.PACKAGE is not None
