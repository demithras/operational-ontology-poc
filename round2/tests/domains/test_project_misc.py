"""Project Ontology: freeze-hash reproduction, lifecycle policy in isolation, Git adapter faults."""
from __future__ import annotations

from domains.project.logic.freeze import freeze_digest
from prj_helpers import Snap, failed_gates, ir_without_preconditions, make

R1 = "researcher-1"


def test_compute_freeze_hash_reproduces_scripts_freeze_protocol_py():
    """sha256 over `path NUL bytes NUL` of the files FREEZE.json lists == protocol_sha256 written by the script."""
    import json
    from domains.project.logic.freeze import ROUND2, git_blob_reader
    fz = json.loads((ROUND2 / "protocol/FREEZE.json").read_text())
    rd = git_blob_reader()
    assert freeze_digest([(f["path"], rd(f["path"])) for f in fz["files"]]) == fz["protocol_sha256"]
    paths = [f["path"] for f in fz["files"]]

    def mut(s):  # an Experiment whose frozen refs are exactly the FREEZE file list, governed by no threshold
        s["ops"].append({"op": "create", "type": "Experiment", "key": "exp-protocol", "props": {
            "id": "exp-protocol", "version": "1", "evidence_schema_ref": ",".join(paths[:-1]), "evaluator_ref": paths[-1]}})
    e, *_ = make(mutator=mut)
    assert e.call_function("compute_freeze_hash", {"experiment": "exp-protocol"}) == fz["protocol_sha256"]
    bad = e.call_function("compute_freeze_hash", {"experiment": "exp-h16-001"})
    assert bad != fz["protocol_sha256"]  # known negative: a different file set hashes differently


# ---- Git adapter faults -------------------------------------------------------------------------
def test_git_timeout_is_outcome_unknown_then_reconciles_after_recovery():
    e, git, _, _ = make()
    git.mode = "timeout"
    rec = e.propose("start_run", {"hypothesis": "H16"}, R1, idempotency_key="r")
    assert rec["state"] == "OUTCOME_UNKNOWN" and not git.commits and len(e.effect_log.entries()) == 0
    assert e.reconcile(rec["exec"])["state"] == "OUTCOME_UNKNOWN"  # nothing was committed: never a fabricated success


def test_git_holding_something_else_reconciles_to_failed():
    e, git, _, _ = make()
    git.mode = "corrupt"
    assert e.propose("start_run", {"hypothesis": "H16"}, R1, idempotency_key="r")["state"] == "RECONCILED_FAILED"


def test_git_commit_observation_lag_leaves_outcome_unknown_then_success():
    e, git, _, _ = make()
    git.observe = False
    rec = e.propose("start_run", {"hypothesis": "H16"}, R1, idempotency_key="r")
    assert rec["state"] == "OUTCOME_UNKNOWN" and len(git.commits) == 1  # the commit exists, nobody observed it yet
    git.observe = True
    assert e.reconcile(rec["exec"])["state"] == "RECONCILED_SUCCESS"


def test_lifecycle_order_policy_alone_denies_an_illegal_transition():
    """Preconditions removed: the allow policy `legal_lifecycle_transition_allowed` (default deny) is the only gate."""
    e, git, _, _ = make(package=ir_without_preconditions("start_run"))
    z = Snap(e, git)
    rec = e.propose("start_run", {"hypothesis": "H15"}, R1, idempotency_key="r")  # EVALUATED -> RUNNING is illegal
    assert rec["state"] == "DENIED" and failed_gates(rec) == ["policy"] and z.unchanged()
    assert e.propose("start_run", {"hypothesis": "H16"}, R1, idempotency_key="r2")["state"] == "RECONCILED_SUCCESS"
