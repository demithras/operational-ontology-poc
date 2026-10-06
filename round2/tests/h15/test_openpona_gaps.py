"""ontology/openpona_gaps.json is well-formed, and render() raises Unrepresentable for a listed gap
(never a lossy render). The mechanism is proven with an injected gap since the committed list may be empty."""
import json

import pytest

import eoo_openpona.gaps as gaps
from eoo_openpona import Unrepresentable, render

from openpona_util import ROOT, load

KEYS = {"ir_path", "reason", "attempted_phrasings", "would_need", "detector"}
NEEDS = {"new_token", "grammar_change", "structural_sidecar", "parser_change", "other"}


def test_gap_file_is_a_list_of_complete_entries():
    data = json.loads((ROOT / "ontology/openpona_gaps.json").read_text())
    assert isinstance(data, list)
    for g in data:
        assert set(g) >= KEYS, g
        assert g["would_need"] in NEEDS and g["attempted_phrasings"], g
        assert g["detector"] in gaps.DETECTORS


def test_every_listed_gap_is_wired_to_render():
    assert len(gaps.gaps()) == len(json.loads((ROOT / "ontology/openpona_gaps.json").read_text()))


def test_injected_gap_makes_render_refuse(monkeypatch):
    monkeypatch.setitem(gaps.DETECTORS, "probe", lambda ir: "hit" if ir["link_types"] else None)
    gaps.gaps.cache_clear()
    monkeypatch.setattr(gaps, "gaps", lambda: [{"ir_path": "link_types[]", "reason": "probe", "detector": "probe"}])
    with pytest.raises(Unrepresentable):
        render(load("ontology/examples/project-domain-minimal.json"))
    render(load("ontology/examples/manufacturing-minimal.json"))  # no link types: renders
