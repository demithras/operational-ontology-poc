"""Level 1 SHACL contract tests (docs/experiment/spec/08_test_strategy.md).

Validates every positive/negative fixture under tests/contracts/shacl/
against the versioned contracts/shapes/v1/*.ttl using pyshacl, purely
in-process (no docker stack). The CI gate from
docs/experiment/spec/13_repository_contract.md ("SHACL negative fixture
unexpectedly conforms") is exactly these negative-fixture assertions.
"""

from __future__ import annotations

import rdflib
import pyshacl
import pytest

from tests.contracts.conftest import negative_fixtures, positive_fixtures


def _validate(fixture_path, ontology_graph: rdflib.Graph, shapes_graph: rdflib.Graph):
    data = rdflib.Graph()
    data.parse(fixture_path, format="turtle")
    data += ontology_graph
    conforms, _report_graph, report_text = pyshacl.validate(
        data,
        shacl_graph=shapes_graph,
        ont_graph=ontology_graph,
        inference=None,
        advanced=True,
    )
    return conforms, report_text


@pytest.mark.parametrize("fixture_path", positive_fixtures(), ids=lambda p: p.name)
def test_positive_fixture_conforms(fixture_path, ontology_graph, shapes_graph):
    conforms, report_text = _validate(fixture_path, ontology_graph, shapes_graph)
    assert conforms, f"{fixture_path.name} was expected to conform but did not:\n{report_text}"


@pytest.mark.parametrize("fixture_path", negative_fixtures(), ids=lambda p: p.name)
def test_negative_fixture_does_not_conform(fixture_path, ontology_graph, shapes_graph):
    conforms, report_text = _validate(fixture_path, ontology_graph, shapes_graph)
    assert not conforms, (
        f"{fixture_path.name} was expected to VIOLATE the shape set (CI gate: "
        f"'SHACL negative fixture unexpectedly conforms') but it conformed."
    )


def test_fixture_directories_are_not_empty():
    # Guards against a future accidental deletion making the parametrized
    # tests above silently collect zero cases (which pytest does not fail
    # on by default) — the honest-failure twin of "0 tests ran" traps.
    assert len(positive_fixtures()) >= 2
    assert len(negative_fixtures()) >= 5
