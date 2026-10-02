"""ENGINE_PREREG ordinary resources: zero handwritten endpoint/tool code, usable through generated tools, Gate-0 file untouched."""
import copy

import pytest

from domains._pack import load_ir
from eoo_h21 import handwritten, replication
from eoo_ir import validate


@pytest.fixture(scope="module")
def payload():
    return handwritten.payload(21, 200)


def test_extended_ir_validates_and_the_gate0_file_is_not_the_extended_one(payload):
    ir = replication.extended_ir()
    assert validate(ir) == [] and {a["id"] for a in ir["actions"]} - {a["id"] for a in load_ir("project")["actions"]} == {"register_replication"}
    assert payload["gate0_files_unchanged"] and "Replication" not in {o["id"] for o in load_ir("project")["object_types"]}
    assert validate(load_ir("project")) == []


def test_no_handwritten_endpoint_or_tool_code_for_the_new_resources(payload):
    assert payload["handwritten_endpoint_or_tool_code_added"] == 0 and payload["toolchain_files_changed"] == []
    assert payload["token_occurrences_in_toolchain_and_domains"] == {}
    assert {"act_register_replication", "call_count_replications", "get_Replication", "list_Replication", "follow_REPLICATES"} <= set(payload["generated_new_tools"])
    assert {"Replication", "Fn_count_replications", "Act_register_replication"} <= set(payload["generated_new_sdk_symbols"])
    assert payload["domain_logic"]["bindings"] == 4 and payload["domain_logic"]["lines_total"] > 10


def test_endpoint_scanner_known_negative_finds_a_planted_endpoint(payload):
    assert payload["handwritten_endpoint_definitions"]["scanner_known_negative_planted_endpoint"] == ["act_register_replication"]
    assert handwritten.endpoint_definitions("class Act_register_replication:\n    pass\n") == ["Act_register_replication"]
    assert handwritten.endpoint_definitions("def helper_for_replication():\n    pass\n") == []


def test_the_new_resources_work_end_to_end_through_the_generated_surface(payload):
    steps = payload["end_to_end"]["steps"]
    assert payload["end_to_end"]["all_ok"] and len(steps) == 5, [s for s in steps if not s["ok"]]


def test_regenerated_surface_still_conforms_and_matches_the_oracle(payload):
    assert payload["regenerated_conformance"]["failed"] == 0 and payload["regenerated_differential"]["mismatching_cases"] == 0


def test_without_the_logic_bindings_the_engine_refuses_to_load():
    """The logic for the new Function/Action is domain logic and is NOT generated: leaving it out is a LoadError, never a silent default."""
    from domains._pack import boot
    from domains.project.pack import build_pack
    from eoo_engine import LoadError
    ir = replication.extended_ir()
    with pytest.raises(LoadError):
        boot("project", build_pack(ir=copy.deepcopy(ir)), package=ir)
