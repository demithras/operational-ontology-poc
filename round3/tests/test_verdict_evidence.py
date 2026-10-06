import itertools
import jsonschema
import pytest
from r3_shared.verdict import (CommonEvaluation, Verdict, DualVerdict, evaluate_common, evaluate_from_mapping)
from r3_shared import evidence

GOOD = dict(protocol_valid=True, required_evidence_complete=True, sample_sufficient=True, reject_hit=False,
            support_hit=True)


def test_known_positive_supported():
    assert evaluate_common(CommonEvaluation(**GOOD)) is Verdict.SUPPORTED


@pytest.mark.parametrize("change,expect", [
    ({"protocol_valid": False}, Verdict.INVALID), ({"reject_hit": True}, Verdict.REJECTED),
    ({"required_evidence_complete": False}, Verdict.INCONCLUSIVE),
    ({"sample_sufficient": False}, Verdict.INCONCLUSIVE), ({"support_hit": False}, Verdict.INCONCLUSIVE),
    ({"protocol_valid": False, "reject_hit": True}, Verdict.INVALID),
    ({"reject_hit": True, "required_evidence_complete": False}, Verdict.REJECTED)])
def test_known_negatives(change, expect):
    assert evaluate_common(CommonEvaluation(**{**GOOD, **change})) is expect


def test_supported_only_when_all_good():
    for combo in itertools.product([True, False, None], repeat=5):
        valid, evid, samp, rej, sup = combo
        want = valid is True and evid is True and samp is True and rej is False and sup is True
        assert (evaluate_common(CommonEvaluation(*combo)) is Verdict.SUPPORTED) == want


def test_none_and_missing_never_supported():
    assert evaluate_from_mapping(None) is Verdict.INVALID
    assert evaluate_from_mapping({}) is Verdict.INVALID
    m = {"protocol_valid": True, "support_hit": True}
    assert evaluate_from_mapping(m) is Verdict.INCONCLUSIVE
    assert evaluate_from_mapping({**m, "required_evidence_complete": None, "sample_sufficient": True,
                                  "reject_hit": False}) is Verdict.INCONCLUSIVE
    assert evaluate_from_mapping(GOOD) is Verdict.SUPPORTED


def test_dual_verdict_missing_is_inconclusive():
    d = DualVerdict(Verdict.SUPPORTED, None, {"forbidden_effects": {"paladin": 0, "conventional": 0}}).to_json()
    assert d["conventional_verdict"] == "INCONCLUSIVE" and d["paladin_verdict"] == "SUPPORTED"
    assert set(d) == {"paladin_verdict", "conventional_verdict", "comparative"}
    assert d["comparative"]["p95_latency_ms"] is None
    with pytest.raises(ValueError):
        DualVerdict("BOGUS", None).to_json()


def _env(**kw):
    base = dict(experiment_id="exp-h23-dev", hypothesis_id="H23", git_commit="abcdef1234", environment={"py": "3"},
                seed=1, attack_class="A1", oracle_version="o1", candidate_version="paladin@x",
                raw_observations=[])
    return evidence.build_envelope(**{**base, **kw})


def test_envelope_valid_hash_and_freeze(tmp_path):
    e = _env()
    evidence.validate_envelope(e)
    assert e["protocol_freeze_hash"] == evidence.protocol_freeze_hash() and len(e["payload_sha256"]) == 64
    sha = evidence.write_envelope(tmp_path / "a.json", e)
    assert sha == e["payload_sha256"]
    with pytest.raises(FileExistsError):
        evidence.write_envelope(tmp_path / "a.json", e)


def test_envelope_negatives():
    with pytest.raises(jsonschema.ValidationError):
        evidence.validate_envelope(_env(hypothesis_id="H99"))
    e = _env()
    e["raw_observations"] = [1]
    with pytest.raises(ValueError):
        evidence.validate_envelope(e)
    e2 = _env()
    del e2["seed"]
    with pytest.raises(jsonschema.ValidationError):
        evidence.validate_envelope(e2)
    with pytest.raises(jsonschema.ValidationError):
        evidence.validate_envelope(_env(candidate_version=None))
