"""Static domain-identity audit: known-positive plants are caught in every branch position; known-negative is clean."""
import ast
import json

import pytest

from eoo_exp.util import ROOT
from eoo_h16.audit import collect_tokens, exempt_words, read_dir, scan_sources
from eoo_h16.detectors import audit_sources

T, EX = collect_tokens(), exempt_words()


@pytest.mark.parametrize("code,position", [
    ('x = 1\nif pkg["domain_id"] == "manufacturing":\n    pass\n', "compare"),
    ('y = {"project-ontology": 1}\n', "dict_key"),
    ('if name in ("Hypothesis", "Part"):\n    pass\n', "membership"),
    ('rules["Verdict"]\n', "subscript"),
    ('name.startswith("operational-ontology-poc")\n', "call_arg"),
    ('z = "attach_evidence"\n', "plain"),
])
def test_planted_identity_is_caught(code, position):
    r = scan_sources({"p.py": code}, T, EX)
    assert r["literal_hits"] >= 1 and any(h["position"] == position for h in r["hits"]), r["hits"]
    assert (r["branch_hits"] >= 1) == (position != "plain")


def test_known_negative_is_clean():
    code = 'def f(kind):\n    """Hypothesis strategies."""\n    if kind == "object_types":\n        return {"actions": 1}["actions"]\n'
    r = scan_sources({"n.py": code}, T, EX)
    assert r["literal_hits"] == 0 and r["branch_hits"] == 0 and len(r["docstring_mentions"]) == 1


def test_real_core_is_clean_and_the_audit_is_not_vacuous():
    a = audit_sources(include_info=True)
    assert a["domain_identity_branches"] == 0 and a["domain_identity_literals"] == 0
    assert a["token_count"] > 150 and a["exempt_words_present_in_tokens"] == []
    counted = [a["scopes"][s] for s in ("engine_core", "ir_core")]
    assert sum(s["string_constants_scanned"] for s in counted) > 1000 and all(s["files_scanned"] > 10 for s in counted)
    assert all(len(s["hits"]) == 0 for s in a["scopes"].values())


def test_tokens_cover_both_domains_and_both_ids():
    assert {"manufacturing", "operational-ontology-poc", "manufacturing-ontology", "project-ontology", "Hypothesis",
            "attach_evidence", "transfer_inventory", "Decision"} <= set(T)
    assert any(o.startswith("manufacturing:") for o in T["Decision"]) and any(o.startswith("project-v2:") for o in T["Decision"])


def test_mutating_each_scanned_file_kind_is_visible():
    src = read_dir(ROOT / "src/eoo_engine")
    mutated = dict(src)
    k = sorted(mutated)[0]
    mutated[k] += '\nif _p == "transfer_inventory":\n    pass\n'
    assert scan_sources(mutated, T, EX)["branch_hits"] == 1
    assert scan_sources(src, T, EX)["branch_hits"] == 0


def test_exempt_words_are_schema_vocabulary_only():
    assert {"object_types", "identity", "authority"} <= EX and "Hypothesis" not in EX
