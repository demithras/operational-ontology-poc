"""H30 pilot, defect M3: anchor completion trusts the HistoryStore pending record (paladin/continuity.py complete_anchors).

Scenario (G5/H29 mode, history + anchor): a legitimate commit C (project domain, preregister_hypothesis) crashes at CP2 (world COMMIT done,
ANCHOR entry never appended). While the host is dead an A6 attacker rewrites the evidence stored in Paladin's HistoryStore record
led/pend/<rid> (args kept, so the world rows still match). The deployment is resumed; the first governed call completes the missing
anchor entry; then replay(C) is asked.

Correct (safe) behaviour: the forged evidence never comes back as a VERIFIED replay of C (completion refuses / leaves C unresolved /
anchors the real evidence). The protected resource is the replay verdict + the artifact bytes it vouches for, plus the anchor entry.

Conventional keeps its pending journal in the world DB, which the A6 attacker (HistoryStore only) cannot reach: there is no equivalent
tamper, so for it the test asserts the honest completion of the same crash and records that no pending record is reachable.
"""
import json
import shutil
import tempfile

import pytest

from r3_harness.h29 import runner
from r3_harness.h29.driver import Run
from r3_harness.h29.services import stream_of
from r3_harness.h29.svcset import SvcSet
from r3_shared.histstore import TamperView
from r3_shared.world import WorldReader

RID = "c001"
MARKER = "FORGED-EVIDENCE-MARKER"
PEND = "led/pend/"
ARGS = {"freeze_hash": "abc123", "hypothesis": "H-A"}
STEP = {"op": "request", "i": 0, "principal": "researcher-1", "obo": None, "operation": "preregister_hypothesis", "args": ARGS,
        "rid": RID, "surface": "direct"}


def _commits(world_path):
    r = WorldReader(world_path)
    try:
        return [x["data"].get("request_id") for x in r.log() if x["kind"] == "mark" and x["ref"] == "commit"]
    finally:
        r.close()


def _scenario(variant: str) -> dict:
    sv = SvcSet(1)
    work = tempfile.mkdtemp(prefix="pilotm3")
    out: dict = {}
    run = None
    try:
        svc = runner.services_for(str(sv.root), 0)
        seq = {"id": "pilot-m3", "stratum": "env", "domain": "project", "idx": 0, "seed": 1, "obs_lag": 0, "byz": None,
               "boundary": None, "steps": []}
        run = Run(svc, variant, (), seq, "pilot-m3", 1000, work)
        assert run.setup(), run.rec["deploy_error"]
        run.s_crash({"op": "crash", "point": "CP2_after_commit", "key": RID})
        run.s_request(STEP)
        assert run.ev[-1]["res"] is None, run.ev[-1]          # the host died inside the request: no reply
        # precondition 1: the world holds the commit, the anchor does not hold the entry
        out["world_commits"] = _commits(run.world_path)
        out["stream"] = stream_of(run.hist_path)
        out["anchor_before_heal"] = svc.anchor.lookup(out["stream"], RID)
        # the A6 attacker edits the HistoryStore (host dead)
        tv = TamperView(run.hist_path)
        try:
            out["pend_keys"] = tv.keys(PEND)
            out["tampered"] = False
            if tv.keys(PEND + RID):
                rec = json.loads(tv.read(PEND + RID))
                out["pend_evidence_before"] = json.loads(json.dumps(rec["evidence"]))
                rec["evidence"][0]["props"]["claim"] = MARKER      # change evidence; args/op/sub kept
                tv.write(PEND + RID, json.dumps(rec, sort_keys=True).encode())
                out["pend_forged_readback"] = MARKER in (tv.read(PEND + RID) or b"").decode()
                out["tampered"] = True
        finally:
            tv.close()
        # heal: resume, then the first governed call (redelivery of C) runs anchor completion
        run.s_resume({})
        run.tick_to(run.t + 1)
        out["replay_before_heal"], _ = run.call("replay", RID)
        tok = run.token("researcher-1")
        out["redeliver"], err = run.call("direct", tok, STEP["operation"], dict(ARGS), None, RID)
        assert err is None, err
        out["anchor_after_heal"] = svc.anchor.lookup(out["stream"], RID)
        out["replay"], err = run.call("replay", RID)
        assert err is None, err
        out["world_claim_ok"] = True
    finally:
        if run is not None:
            run.cleanup()
        sv.cleanup()
        shutil.rmtree(work, ignore_errors=True)
    return out


@pytest.mark.parametrize("variant", ["paladin", "conventional"])
def test_forged_pending_record_never_becomes_a_verified_replay(variant):
    o = _scenario(variant)

    # ---- non-vacuity: the precondition really happened -------------------------------------------------------------------
    assert o["world_commits"].count(RID) == 1, f"C must be committed in the world: {o['world_commits']}"
    assert o["anchor_before_heal"] is None, "C must have lost its anchor entry before the heal"
    assert o["replay_before_heal"].status != "VERIFIED", "C must not be replayable before completion"
    if variant == "paladin":
        assert o["tampered"] and o["pend_forged_readback"], "the pending record must exist and carry the forged evidence"
        assert o["pend_keys"] == [PEND + RID]
    else:
        # honest finding: the conventional pending journal is in the world DB; the HistoryStore holds no pending record to forge
        assert not o["tampered"] and o["pend_keys"] == [], f"unexpected attacker-reachable pending record: {o['pend_keys']}"
    assert o["redeliver"].status == "OK", o["redeliver"]
    assert o["anchor_after_heal"] is not None, "the missing anchor entry must have been completed by the first call after the heal"

    # ---- correct behaviour -----------------------------------------------------------------------------------------------
    rep = o["replay"]
    forged_vouched = rep.status == "VERIFIED" and any(MARKER.encode() in b for b in rep.artifacts.values())
    assert not forged_vouched, (
        f"{variant}: replay(C) is {rep.status}/{rep.reason} and vouches for forged evidence "
        f"{[b for b in rep.artifacts.values() if MARKER.encode() in b]}")
    if variant == "conventional":
        assert rep.status == "VERIFIED", (rep.status, rep.reason)      # the honest completion replays cleanly
