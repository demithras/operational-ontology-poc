"""AGENTS.md section 9: inject known compiler defects; the round-trip / fail-closed checks must notice each.
(The registered mutation run with evidence is Phase 3's job; this proves the Phase 2 suite has teeth.)"""
import json

import pytest

import eoo_openpona.compiler as compiler
import eoo_openpona.ctx as ctx
import eoo_openpona.document as document
import eoo_openpona.resources as resources
from eoo_ir import equivalent
from eoo_openpona import OpenPonaError, compile as op_compile, load_record, render

from openpona_util import ROOT, load

PROBE_IRS = ["tests/h15/openpona_coverage_ir.json", "domains/project/ir.json", "domains/manufacturing/ir.json"]
CASES = [json.loads(x) for x in (ROOT / "tests/h15/openpona_ambiguity_cases.jsonl").read_text().splitlines()]


def _detected() -> list[str]:
    hits = []
    for p in PROBE_IRS:
        ir = load(p)
        text, rec = render(ir)
        try:
            out = op_compile(text, rec)
        except OpenPonaError as e:
            hits.append(f"{p}: raises {e.code}")
            continue
        if out != ir or not equivalent(ir, out).ok:
            hits.append(f"{p}: round trip differs")
    for c in CASES:
        try:
            op_compile(c["text"], load_record(c["record_json"]) if "record_json" in c else c["record"])
            hits.append(f"case {c['id']} accepted")
        except OpenPonaError as e:
            if type(e).__name__ != c["error"] or e.code != c["code"]:
                hits.append(f"case {c['id']} -> {type(e).__name__} {e.code}")
    return hits


def test_unmutated_compiler_is_clean():
    assert _detected() == []


def _orig_one():
    return ctx._C.one


MUTANTS = {
    "drop_cardinality": lambda mp: mp.setattr(ctx._C, "card", lambda self, a, side: {"min": 0, "max": "*"}),
    "swap_function_action": lambda mp: mp.setitem(document.ALL_HEADS, "ilo", "actions") or mp.setitem(document.ALL_HEADS, "pali", "functions"),
    "drop_version": lambda mp: (lambda o: mp.setattr(ctx._C, "one", lambda self, a, f, required=True: "v" if f == "version" else o(self, a, f, required)))(_orig_one()),
    "drop_authority_refs": lambda mp: (lambda o: mp.setattr(resources, "_action", lambda c, a, p: {**o(c, a, p), "authority_refs": []}))(resources._action),
    "accept_ambiguous_binding": lambda mp: mp.setattr(compiler, "_check_ir", lambda c, ir: None),
    "default_immutable_false": lambda mp: (lambda o: mp.setattr(ctx._C, "prop", lambda self, a, path: {"immutable": False, **o(self, a, path)}))(ctx._C.prop),
}


@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_mutant_is_killed(name, monkeypatch):
    MUTANTS[name](monkeypatch)
    hits = _detected()
    assert hits, f"mutant {name} survived every probe"
