"""H15 v2 harness: the v1 path is unchanged (against the committed exp-h15-002 evidence), the surface switch, the v2
evaluator's amendments (pin, prereg, meaning rule -> R3/S4) with known-negatives, and a tiny v2 end-to-end run."""
import json
import subprocess
import sys

import pytest

from eoo_h15 import ambiguity, candidate, domains, evaluate_v2, run, surfaces
from eoo_h15.util import canon, sha_file

from evidence_fixture import build
from openpona_util import ROOT, load

EXP = ROOT / "experiments/h15/exp-h15-002"


def _committed(f):
    return json.loads((EXP / f).read_text())["payload"]


def test_v1_path_reproduces_committed_exp_h15_002_evidence():
    assert not candidate.is_v2() and surfaces.SURFACES["openpona"] is surfaces.OPENPONA
    assert canon(ambiguity.declared_openpona()) == canon(_committed("ambiguity-corpus.json")["declared"]["openpona"])
    assert canon(domains.run()) == canon(_committed("real-domain-roundtrip.json"))
    dom = {d: load(f"domains/{d}/ir.json") for d in domains.DOMAINS}
    assert canon(run._sidecar(dom, [])["domains"]) == canon(_committed("sidecar-audit.json")["domains"])


def test_surface_switch_and_restore():
    try:
        candidate.use("openpona2")
        assert candidate.is_v2() and surfaces.SURFACES["openpona"] is surfaces.OPENPONA2
        assert ambiguity.declared_openpona()["total"] >= 36
        r = domains.run()
        assert all(r[d]["openpona"]["equivalent"] and r[d]["openpona"]["committed_equals_fresh_render"] for d in r)
    finally:
        candidate.use("openpona")
    assert surfaces.SURFACES["openpona"] is surfaces.OPENPONA
    with pytest.raises(ValueError):
        candidate.use("nope")


# ---------------------------------------------------------------- v2 evaluator on synthetic evidence
PIN = "f" * 64


def _v2_dir(tmp, meaning_ok=True, drop_meaning=False, prov=None):
    def mutate(pay):
        if not drop_meaning:
            pay["sidecar-audit.json"]["meaning_rule"] = {"ok": meaning_ok, "verdict": "x", "phrase_table_size": 259,
                                                         "distinct_phrases_total": 200, "packages": 10, "sizes": 3,
                                                         "sizes_over_bound": [] if meaning_ok else [9]}
    base = {"candidate_surface": "openpona2", "candidate_combined_sha256": PIN,
            "h15_v2_prereg_sha256": sha_file(ROOT / "protocol/H15_V2_PREREG.json")}
    return build(tmp, mutate=mutate, prov_for=lambda f: {**base, **(prov or {})})


@pytest.fixture
def pin(tmp_path):
    p = tmp_path / "pin.json"
    p.write_text(json.dumps({"combined_sha256": PIN, "files": []}))
    return p


def _pred(v, pid):
    return next(r["value"] for k in v["predicates"] for r in v["predicates"][k] if r["id"] == pid)


def test_v2_known_positive_is_supported(tmp_path, pin):
    d = _v2_dir(tmp_path / "e")
    assert evaluate_v2.evidence_surface(d) == "openpona2"
    v = evaluate_v2.evaluate(d, candidate_pin=pin)
    assert v["verdict"] == "SUPPORTED", (v["problems"], v["protocol_mismatches"])
    assert _pred(v, "R3") is False and _pred(v, "S4") is True and v["numbers"]["meaning_rule"]["ok"] is True


def test_meaning_rule_violation_rejects(tmp_path, pin):
    v = evaluate_v2.evaluate(_v2_dir(tmp_path / "e", meaning_ok=False), candidate_pin=pin)
    assert v["verdict"] == "REJECTED" and _pred(v, "R3") is True and _pred(v, "S4") is False


def test_missing_meaning_rule_is_never_supported(tmp_path, pin):
    v = evaluate_v2.evaluate(_v2_dir(tmp_path / "e", drop_meaning=True), candidate_pin=pin)
    assert v["verdict"] != "SUPPORTED" and _pred(v, "R3") is None and _pred(v, "S4") is None


@pytest.mark.parametrize("prov", [{"candidate_combined_sha256": "0" * 64}, {"h15_v2_prereg_sha256": "0" * 64},
                                  {"candidate_surface": "openpona"}])
def test_v2_protocol_mismatch_is_invalid(tmp_path, pin, prov):
    v = evaluate_v2.evaluate(_v2_dir(tmp_path / "e", prov=prov), candidate_pin=pin)
    assert v["verdict"] == "INVALID" and _pred(v, "V1") is True


def test_missing_pin_is_invalid(tmp_path):
    v = evaluate_v2.evaluate(_v2_dir(tmp_path / "e"), candidate_pin=tmp_path / "absent.json")
    assert v["verdict"] == "INVALID"


def test_v1_evidence_still_goes_to_the_v1_evaluator(tmp_path):
    d = build(tmp_path / "v1")
    assert evaluate_v2.evidence_surface(d) == "openpona"


# ---------------------------------------------------------------- tiny v2 end-to-end
@pytest.fixture(scope="module")
def tiny_v2(tmp_path_factory):
    root = tmp_path_factory.mktemp("exp2")
    pin = root / "pin.json"
    w = subprocess.run([sys.executable, str(ROOT / "scripts/h15_v2_candidate.py"), "--write", str(pin)],
                       capture_output=True, text=True, timeout=120)
    assert w.returncode == 0, w.stderr
    cmd = [sys.executable, str(ROOT / "scripts/run_h15.py"), "--surface", "openpona2", "--candidate-pin", str(pin),
           "--exp-id", "exp-tiny2", "--seed", "15", "--n", "12", "--out-root", str(root)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1500)
    return root, pin, r


def test_tiny_v2_run_is_valid_and_inconclusive(tiny_v2):
    root, pin, r = tiny_v2
    assert r.returncode == 0, r.stderr[-2000:]
    d = root / "exp-tiny2"
    rec = json.loads((d / "sidecar-audit.json").read_text())
    assert rec["candidate_surface"] == "openpona2" and rec["payload"]["meaning_rule"]["ok"] is True
    v = evaluate_v2.evaluate(d, candidate_pin=pin)
    assert v["verdict"] == "INCONCLUSIVE" and v["common"]["protocol_valid"] is True, v["protocol_mismatches"]
    assert _pred(v, "R3") is False and v["numbers"]["generated_valid_cases"] == 12


def test_v2_run_refuses_without_a_pin(tiny_v2):
    root, _, _ = tiny_v2
    r = subprocess.run([sys.executable, str(ROOT / "scripts/run_h15.py"), "--surface", "openpona2", "--candidate-pin",
                        str(root / "absent.json"), "--exp-id", "exp-nopin", "--seed", "1", "--n", "2", "--out-root",
                        str(root)], capture_output=True, text=True, timeout=600)
    assert r.returncode != 0 and "REFUSED" in (r.stdout + r.stderr)
