"""Clean build of both domains + type / cardinality / Function-vs-Action conformance (and that the checker is not vacuous)."""
import dataclasses
import tempfile

import pytest

from eoo_h21 import conformance
from eoo_toolchain import build, load_generated
from eoo_toolchain.runtime import ActionRequest, FunctionCall

DOMAINS = ("manufacturing", "project")


@pytest.mark.parametrize("dom", DOMAINS)
def test_generated_surface_conforms_to_the_ir(built, dom):
    ir, _d, _inv, sdk, _c, _s = built[dom]
    r = conformance.check(ir, sdk)
    assert r["checks"] > 250 and r["failed"] == 0 and r["conformance"] == 1.0, r["failures"]


@pytest.mark.parametrize("dom", DOMAINS)
def test_rebuild_is_byte_identical_and_only_generated_files_exist(built, dom):
    ir, d, inv, *_ = built[dom]
    again = build(ir, tempfile.mkdtemp())
    assert again["files"] == inv["files"]
    assert sorted(p.name for p in (d / inv["package"]).glob("*.py")) == sorted(inv["files"])


@pytest.mark.parametrize("dom", DOMAINS)
def test_function_and_action_types_are_distinct(built, dom):
    ir, _d, _inv, sdk, *_ = built[dom]
    for f in ir["functions"]:
        c = getattr(sdk, "Fn_" + f["id"])
        assert issubclass(c, FunctionCall) and not issubclass(c, ActionRequest) and hasattr(c, "call") and not hasattr(c, "propose")
    for a in ir["actions"]:
        c = getattr(sdk, "Act_" + a["id"])
        assert issubclass(c, ActionRequest) and not issubclass(c, FunctionCall) and hasattr(c, "propose") and not hasattr(c, "call")
        assert c.CAPABILITY == "action:" + a["id"]


def test_cardinality_decides_single_vs_list_accessors(built):
    ir, _d, _inv, sdk, *_ = built["project"]
    lk = next(x for x in ir["link_types"] if x["id"] == "HAS_RIVAL")  # Hypothesis -> Rival, to side exactly one
    assert lk["from_cardinality"]["max"] == "*" and lk["to_cardinality"]["max"] == 1
    assert sdk.Hypothesis.out_HAS_RIVAL.__annotations__["return"] == "list[Rival]"
    assert sdk.Rival.in_HAS_RIVAL.__annotations__["return"] == "Optional[Hypothesis]"

    class Rec:
        calls = []

        def follow(self, *a, **k):
            self.calls.append("follow")
            return []

        def follow_one(self, *a, **k):
            self.calls.append("follow_one")
            return None
    c = Rec()
    sdk.Hypothesis(id="h", claim="c", phase="DRAFT").out_HAS_RIVAL(c)
    sdk.Rival(id="r", statement="s").in_HAS_RIVAL(c) if "statement" in {f.name for f in dataclasses.fields(sdk.Rival)} else None
    assert c.calls[0] == "follow"


def test_enum_constraints_and_optionality_are_typed(built):
    _ir, _d, _inv, sdk, *_ = built["project"]
    ann = sdk.Hypothesis.__annotations__
    assert ann["phase"].startswith("Literal[") and "PREREGISTERED" in ann["phase"] and ann["freeze_hash"] == "Optional[str]"
    with pytest.raises(TypeError):
        sdk.Act_create_hypothesis()  # required input missing: the generated type refuses it


@pytest.mark.parametrize("tamper", ["drop_field", "rename_class", "swap_base", "drop_accessor"])
def test_conformance_checker_known_negatives(tamper):
    """A hand-damaged SDK must fail conformance (the checker finds each defect class)."""
    from domains._pack import load_ir
    ir = load_ir("project")
    d = tempfile.mkdtemp()
    inv = build(ir, d)
    sdk, *_ = load_generated(d, inv["package"])
    if tamper == "drop_field":
        del sdk.Hypothesis.__annotations__["claim"]
    elif tamper == "rename_class":
        del sdk.Fn_evidence_count
    elif tamper == "swap_base":
        sdk.Fn_evidence_count.__bases__ = (ActionRequest,)
    else:
        del sdk.Hypothesis.out_HAS_RIVAL
    assert conformance.check(ir, sdk)["failed"] > 0
