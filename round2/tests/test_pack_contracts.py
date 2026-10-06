import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def contracts():
    return [json.loads(p.read_text()) for p in sorted((ROOT / "hypotheses").glob("h*/contract.json"))]


def test_ids_are_h15_to_h22():
    assert [x["id"] for x in contracts()] == [f"H{i}" for i in range(15, 23)]


def test_every_contract_has_strong_rival_and_mutation_proof():
    for x in contracts():
        assert x["null_hypothesis"]
        assert x["rivals"]
        assert x["falsifiers"]
        assert x["python_hypothesis_role"]["mutation_proof"]


def test_h15_does_not_assume_openpona_oracle():
    h15 = contracts()[0]
    assert "independent" in h15["oracle"].lower()
    assert "openpona token logic" in h15["oracle"].lower()


def test_h22_cannot_claim_two_domain_generalization():
    thresholds = json.loads((ROOT / "protocol" / "thresholds.json").read_text())
    assert thresholds["H22"]["min_real_domains_for_verdict"] >= 3
