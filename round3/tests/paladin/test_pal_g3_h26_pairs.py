"""H26 (PROT-H26): paired worlds differing ONLY in a protected fact give byte-identical canonical observations on every
low channel (R26-1/R26-2/R26-3). One test per fact kind (F, E, L, D, G, C); canaries are scanned over every response."""
import json

import pytest

from g3_pairs import divergences, run_pair

CANARY = ["cv-7a1c3e90", "cv-b22f4d17", "7000001", "7000002"]


def seed(r):
    return r.store.handle("seed")


def scan(pair):
    blob = json.dumps(pair)
    return [c for c in CANARY if c in blob]


def test_F_hidden_field_value(tmp_path):
    def hidden(r, k):
        seed(r).update("Component", "cmp-live", {"path": CANARY[k]})            # type hidden from viewer-1
        seed(r).update("Experiment", "E-A@v1", {"freeze_hash": CANARY[k]})
    pair = run_pair(tmp_path, hidden)
    assert divergences(pair) == [] and scan(pair) == []


def test_F_hidden_field_of_a_visible_object(tmp_path):
    def hidden(r, k):
        seed(r).update("Experiment", "E-A@v1", {"freeze_hash": CANARY[k]})       # visible to researchers, field denied
        seed(r).update("Evidence", "EV-C1", {"environment": CANARY[k]})          # field not in the researcher's reveal list
    pair = run_pair(tmp_path, hidden, who="researcher-2")
    assert divergences(pair) == [] and scan(pair) == []


def test_E_hidden_existence(tmp_path):
    def hidden(r, k):
        seed(r).create("Failure", f"cv-x{k + 1}", {"id": f"cv-x{k + 1}"})        # same shape: one create each
    pair = run_pair(tmp_path, hidden)
    assert divergences(pair) == [] and scan(pair) == []


def test_L_hidden_link(tmp_path):
    def hidden(r, k):
        seed(r).link("DETECTED_BY", "Failure:f-1", "Test:t-1")
        if k:
            seed(r).unlink("DETECTED_BY", "Failure:f-1", "Test:t-1")
            seed(r).link("DETECTED_BY", "Failure:f-1", "Test:t-1")
        seed(r).link("VALIDATES", "Test:t-1", f"Component:{'cmp-live' if k else 'cmp-orphan'}")
    pair = run_pair(tmp_path, hidden)
    assert divergences(pair) == []


def test_D_hidden_decision(tmp_path):
    def hidden(r, k):   # another principal's request differs in its (hidden) target; same count and status class
        r.dep.direct(r.tok("researcher-1"), "attach_evidence", {"hypothesis": "H-C", "evidence": ["EV-C1", "EV-C2"][k]},
                     request_id="hi-1")
    pair = run_pair(tmp_path, hidden)
    assert divergences(pair) == []


def test_G_hidden_case(tmp_path):
    def hidden(r, k):   # a case the observer cannot see: judgments differ
        r.propose("researcher-1", "hc", "edit_threshold", {"threshold": "T-A", "value": {"min": 12}})
        r.judge("agent-draft-1", "hc", ["concur", "dissent"][k], merit=CANARY[k])
    pair = run_pair(tmp_path, hidden, who="researcher-2", governance="fixture")
    assert divergences(pair) == [] and scan(pair) == []


def test_aa_control_same_world_twice(tmp_path):
    pair = run_pair(tmp_path, lambda r, k: seed(r).update("Component", "cmp-live", {"path": "same"}))
    assert divergences(pair) == []


def test_probe_is_not_vacuous_a_low_fact_does_diverge(tmp_path):
    """Known negative for the comparison itself: a LOW difference (a public Threshold value) must be seen as a divergence."""
    pair = run_pair(tmp_path, lambda r, k: seed(r).update("Threshold", "T-A", {"value": {"min": 40 + k}}))
    assert "read:Threshold:T-A" in divergences(pair)
    assert "poll" in divergences(pair)
