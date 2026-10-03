"""Git-backed store: one commit per action with provenance, deterministic projection, stale / concurrent / conflicting writes."""
import copy
import subprocess
from pathlib import Path

import pytest

from eoo_engine import ENGINE_VERSION, ProvenanceEnvelope, render_envelope
from eoo_engine.state import State
from eoo_engine.store import would_be
from eoo_engine_git import ConflictError, GitStore, RowRejected, artifact_digest
from eoo_engine_git import layout
from eoo_engine_git.errors import BatchError
from eoo_h18.rig import EooRig, PRINCIPAL, trailers
from domains._pack import load_ir

R = PRINCIPAL
EV = ["exp-h15-002/real-domain-roundtrip.json", "exp-h15-002/generated-roundtrip.json", "exp-h15-002/ambiguity-corpus.json"]


@pytest.fixture()
def fresh(reader, tmp_path):
    r = EooRig(tmp_path, reader=reader, h15_state="RUNNING")
    r.store.import_ops(r.base_ops, source="t", ref="refs/heads/main", parent=r.root)
    return r


def _log(repo, ref="refs/heads/main"):
    return subprocess.run(["git", "-C", str(repo), "log", "--format=%H", ref], capture_output=True, text=True).stdout.split()


def test_roundtrip_files_state_files_is_identity(rig):
    files = rig.store.files_at(rig.root)
    st = rig.store.state_at(rig.root)
    assert layout.serialize(st) == files and layout.to_ops(files) == rig.store.seed_ops_at(rig.root)


def test_projection_boots_the_same_engine_state_as_the_direct_seed(rig):
    from domains._pack import boot
    from domains.project.pack import build_pack
    e1 = rig.engine("refs/heads/main")
    e2 = boot("project", build_pack(rig.seed, reader=rig.reader))
    assert e1.state().state_hash() == e2.state().state_hash()


def test_one_commit_per_action_with_execution_base_and_provenance(fresh):
    st, repo = fresh.store, fresh.store.repo.path
    head0, e = st.head("refs/heads/main"), fresh.engine("refs/heads/main")
    rec = e.propose("attach_evidence", {"hypothesis": "H15", "evidence": EV[0]}, R, idempotency_key="a")
    assert rec["state"] == "RECONCILED_SUCCESS"
    head1 = st.head("refs/heads/main")
    assert _log(repo)[0] == head1 and _log(repo)[1] == head0  # exactly one new commit on top of the base
    t = trailers(subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%B", head1], capture_output=True, text=True).stdout)
    assert (t["EOO-Execution"], t["EOO-Action"], t["EOO-Engine-Version"]) == (rec["exec"], "attach_evidence", ENGINE_VERSION)
    assert {r["commit"] for r in rec["responses"].values()} == {head1} and len(rec["responses"]) == 3  # 3 effects, ONE commit
    # v1.2: the base is a Git fact returned in the response (recorded by the Engine), not rendered into the message
    assert {r["base"] for r in rec["responses"].values()} == {head0} and {r["head_at_write"] for r in rec["responses"].values()} == {head0}
    first = sorted(rec["envelopes"])[0]  # the effect whose apply wrote the commit: its envelope text IS the message, byte for byte
    assert st.repo.read_commit(head1)["message"] == render_envelope(ProvenanceEnvelope.from_plain(rec["envelopes"][first]))
    assert [x[0] for x in rec["envelopes"][first]["execution_effects"]] == sorted(rec["responses"])  # the batch is named
    assert subprocess.run(["git", "-C", str(repo), "fsck", "--strict"], capture_output=True).returncode == 0


def test_denied_action_writes_nothing(fresh):
    st, e = fresh.store, fresh.engine("refs/heads/main")
    head0 = st.head("refs/heads/main")
    rec = e.propose("edit_threshold", {"threshold": "H17.min_state_machine_examples", "value": 1}, R, idempotency_key="t")
    assert rec["state"] == "DENIED" and st.head("refs/heads/main") == head0 and not e.effect_log.entries()


def test_rebuild_from_the_same_commit_is_pure_and_clock_free(fresh, reader):
    st = fresh.store
    fresh.engine("refs/heads/main").propose("attach_evidence", {"hypothesis": "H15", "evidence": EV[0]}, R, idempotency_key="a")
    head = st.head("refs/heads/main")
    other = GitStore(type(st.repo)(st.repo.path), load_ir("project"), engine_version="other", clock=lambda: "2030-01-01T00:00:00+00:00")
    assert other.canonical_hash(head) == st.canonical_hash(head) == artifact_digest(st.files_at(head))
    assert other.state_at(head).state_hash() == st.state_at(head).state_hash()


def test_stale_compatible_concurrent_changes_merge_on_a_linear_history(fresh):
    st, ref = fresh.store, "refs/heads/main"
    base = st.head(ref)
    a, b = fresh.engine(ref, writer="wA", base=base), fresh.engine(ref, writer="wB", base=base)
    assert a.propose("attach_evidence", {"hypothesis": "H15", "evidence": EV[0]}, R, idempotency_key="a")["state"] == "RECONCILED_SUCCESS"
    ha = st.head(ref)
    rb = b.propose("attach_evidence", {"hypothesis": "H15", "evidence": EV[1]}, R, idempotency_key="b")
    assert rb["state"] == "RECONCILED_SUCCESS" and st.log[-1]["merge"] == "compatible" and st.log[-1]["parent"] == ha
    files = st.files_at(st.head(ref))
    assert sum(1 for p in files if p.startswith("ontology/links/PRODUCES/") and "exp-h15-002" in p) == 2
    resp = list(rb["responses"].values())  # v1.2: base / head at write / merge mode come back in the adapter response
    assert {r["base"] for r in resp} == {base} and {r["head_at_write"] for r in resp} == {ha} and {r["merge"] for r in resp} == {"compatible"}
    assert {r["commit"] for r in resp} == {st.head(ref)} and trailers(st.repo.read_commit(st.head(ref))["message"])["EOO-Execution"] == rb["exec"]


def test_conflicting_concurrent_change_is_explicit_and_loses_nothing(fresh):
    st, ref = fresh.store, "refs/heads/main"
    st.import_ops(copy.deepcopy([dict(o, props={**o["props"], "phase": "DRAFT"}) if (o["op"] == "create" and o["type"] == "Hypothesis" and o["key"] == "H16") else o
                                 for o in fresh.base_ops]), source="draft", ref=ref, parent=fresh.root)
    base = st.head(ref)
    a, b = fresh.engine(ref, writer="wA", base=base), fresh.engine(ref, writer="wB", base=base)
    thr = sorted(k for (t, k) in st.state_at(base).objects if t == "Threshold" and k.startswith("H16."))[0]
    assert a.propose("edit_threshold", {"threshold": thr, "value": 111}, R, idempotency_key="a")["state"] == "RECONCILED_SUCCESS"
    head_a = st.head(ref)
    rb = b.propose("edit_threshold", {"threshold": thr, "value": 222}, R, idempotency_key="b")
    assert rb["state"] == "OUTCOME_UNKNOWN" and any("ConflictError" in x["error"] for x in rb["adapter_errors"])
    assert st.head(ref) == head_a and st.conflicts[-1]["conflicts"][0]["property"] == "value"
    assert st.conflicts[-1]["conflicts"][0]["ours"] == 222 and st.conflicts[-1]["conflicts"][0]["theirs"] == 111
    assert st.state_at(head_a).objects[("Threshold", thr)]["props"]["value"] == 111  # the winner is untouched


def test_never_merge_mode_turns_every_stale_write_into_a_conflict(fresh):
    st, ref = fresh.store, "refs/heads/main"
    base = st.head(ref)
    fresh.merge_mode = "never"
    a, b = fresh.engine(ref, writer="wA", base=base), fresh.engine(ref, writer="wB", base=base)
    a.propose("attach_evidence", {"hypothesis": "H15", "evidence": EV[0]}, R, idempotency_key="a")
    head_a = st.head(ref)
    rb = b.propose("attach_evidence", {"hypothesis": "H15", "evidence": EV[1]}, R, idempotency_key="b")
    assert rb["state"] == "OUTCOME_UNKNOWN" and st.head(ref) == head_a and st.conflicts[-1]["conflicts"][0]["kind"] == "stale_base"


def test_integrity_of_a_row_is_enforced_by_the_store(fresh):
    st, ref = fresh.store, "refs/heads/main"
    base = st.head(ref)
    meta = {"execution": "x9", "action": "a", "effects": ["x9/e0"]}
    with pytest.raises(RowRejected, match="immutable"):
        st.commit_rows(rows=[("Evidence", {"$key": EV[0], "payload_hash": "tampered"})], base=base, writer="w", meta=meta, message="t\n")
    with pytest.raises(RowRejected, match="undeclared"):
        st.commit_rows(rows=[("Hypothesis", {"$key": "H15", "nonsense": 1})], base=base, writer="w", meta=meta, message="t\n")
    assert st.head(ref) == base


def test_partial_batch_is_refused_never_split_into_two_commits(fresh):
    from eoo_engine_git import GitAdapter
    ad = GitAdapter(fresh.store, "w", base=fresh.store.head("refs/heads/main"))
    with pytest.raises(BatchError):
        ad.apply({"effect_id": "x1/e0", "execution": "x1", "action": "attach_evidence", "operation": "git_change", "target": "Evidence"}, {"id": "k"})
    assert len(fresh.store.log) == 0


def test_store_is_domain_blind_it_also_holds_the_manufacturing_package(tmp_path):
    import json
    from eoo_engine import ENGINE_VERSION
    ir = load_ir("manufacturing")
    seed = json.loads((Path(__file__).resolve().parents[2] / "domains/manufacturing/seed.json").read_text())
    s = GitStore.init(tmp_path / "m", ir, engine_version=ENGINE_VERSION, clock=lambda: "2026-10-02T00:00:00+00:00")
    c = s.import_ops(seed["ops"], source="mfg")
    st, errs = would_be(State(s.model), s.seed_ops_at(c))
    assert not errs and layout.serialize(st) == s.files_at(c) and len(s.seed_ops_at(c)) == len(seed["ops"])
