"""The H18 oracle: independent of the runtime, agrees with the named reference model, and says 'illegal' for every hostile op."""
import copy

import pytest
from hypothesis import given, strategies as st

from eoo_exp.util import load_oracle
from eoo_h18.extras import oracle_imports
from hdd.verdict import CommonEvaluation, evaluate_common

W = load_oracle("h18", "world")


def case(**kw):
    base = {"subject": "H16", "phase0": "DRAFT", "complete": {k: True for k in W.CORE_LINKS},
            "evidence": [{"id": f"ev-gen-{i}", "pin": "good", "tag": "s"} for i in range(3)] + [{"id": "ev-gen-bad", "pin": "version", "tag": "s"}],
            "decision": {"id": "dec-gen", "rationale": "x"}, "components": [{"id": "cmp-gen-0"}], "ops": [],
            "facts": {"exp": "exp-h16-001", "threshold": "H16.t", "threshold_value": 5, "cv": "cv-H16", "other": "H17", "commit": "c",
                      "components": {"cmp-a": ["H15"], "cmp-legacy": []}}}
    base.update(kw)
    return base


def run(ops, **kw):
    w = W.World(case(**kw))
    return [w.step(op)[0] for op in ops], w


PRE = {"k": "preregister", "freeze": "junk", "freeze_value": "fh-1"}


def test_oracle_imports_no_runtime_code():
    r = oracle_imports()
    assert r["independent"], r["forbidden"]
    assert any("hdd" in m for m in r["files"]["world.py"]), "the oracle must use the named reference model"


def test_the_full_legal_path_is_legal_and_derives_the_expected_verdict():
    ops = [PRE, {"k": "start"}] + [{"k": "attach", "ev": f"ev-gen-{i}"} for i in range(3)] + [{"k": "evaluate"}, {"k": "supersede", "succ": "other"}]
    legal, w = run(ops)
    assert all(legal) and w.verdicts == ["SUPPORTED"] and w.phase == "SUPERSEDED" and w.successor == "H17"


@pytest.mark.parametrize("name,ops,idx", [
    ("post_freeze_threshold_edit", [PRE, {"k": "edit_threshold", "value": 9}], 1),
    ("start_before_preregistration", [{"k": "start"}], 0),
    ("evidence_wrong_version", [PRE, {"k": "start"}, {"k": "attach", "ev": "ev-gen-bad"}], 2),
    ("evidence_while_not_running", [PRE, {"k": "attach", "ev": "ev-gen-0"}], 1),
    ("forced_verdict", [PRE, {"k": "start"}, {"k": "forced_verdict", "value": "SUPPORTED"}], 2),
    ("supersede_before_evaluation", [PRE, {"k": "supersede", "succ": "other"}], 1),
    ("supersede_self", [PRE, {"k": "start"}, {"k": "evaluate"}, {"k": "supersede", "succ": "self"}], 3),
    ("blank_freeze", [{"k": "preregister", "freeze": "blank", "freeze_value": ""}], 0),
    ("overwrite_experiment_version", [PRE, {"k": "new_version", "exp": "base"}, {"k": "new_version", "exp": "base"}], 2),
    ("new_version_while_draft", [{"k": "new_version", "exp": "base"}], 0),
    ("flag_a_non_orphan", [{"k": "flag", "cmp": "cmp-a"}], 0)])
def test_every_hostile_op_is_illegal(name, ops, idx):
    legal, _ = run(ops)
    assert legal[idx] is False, name
    assert all(legal[:idx]), f"{name}: the prefix must be legal so the hostile op is the first illegal one"


def test_incomplete_contract_cannot_be_preregistered():
    for missing in W.CORE_LINKS:
        legal, _ = run([PRE], complete={**{k: True for k in W.CORE_LINKS}, missing: False})
        assert legal == [False], missing


def test_illegal_op_leaves_the_world_unchanged():
    w = W.World(case())
    before = copy.deepcopy(w.summary())
    w.step({"k": "start"})
    assert w.summary() == before


def test_orphans_appear_when_the_only_hypothesis_is_superseded():
    ops = [PRE, {"k": "start"}, {"k": "evaluate"}, {"k": "supersede", "succ": "other"}, {"k": "flag", "cmp": "cmp-gen-0"}]
    legal, w = run(ops)
    assert legal == [True] * 5 and w.flagged == {"cmp-gen-0"}


@given(st.lists(st.sampled_from("srn"), max_size=6))
def test_expected_verdict_equals_the_pack_wide_precedence(tags):
    n = len(tags)
    flags = CommonEvaluation(protocol_valid=True, required_evidence_complete=n >= 2, sample_sufficient=True, reject_hit="r" in tags,
                             support_hit=n >= 1 and all(t == "s" for t in tags))
    assert W.expected_verdict(tags) == evaluate_common(flags).value
