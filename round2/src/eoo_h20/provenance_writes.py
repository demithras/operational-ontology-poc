"""Read back the provenance-bearing artifact an adapter wrote (Git commit message), for the byte-for-byte verbatim check.

Harness side only: the readers look at the external system (GitStore objects, GitFake's commit log), never at the Engine.
"""
from __future__ import annotations

from eoo_h17.drivers import new_driver
from eoo_h17.scenarios import ALL


def written_text(adapter, commit: str):
    """The commit message the external system holds for ``commit``; None when this adapter has no readable commit store."""
    store = getattr(adapter, "store", None)
    if store is not None and hasattr(getattr(store, "repo", None), "read_commit"):  # GitAdapter over GitStore
        return store.repo.read_commit(commit)["message"]
    commits = getattr(adapter, "commits", None)
    if isinstance(commits, list):  # GitFake
        for c in commits:
            if isinstance(c, dict) and c.get("sha") == commit and "message" in c:
                return c["message"]
    return None


def _git_fake_run(tracer_cls, tamper: bool) -> dict:
    from domains.project.adapters import git_fake as gf
    t = tracer_cls()
    orig_apply = gf.GitFake.apply
    with t.installed():
        if tamper:  # known-negative: the adapter appends its own line (a label NOT starting with EOO-) to what it writes
            gf.GitFake.apply = lambda self, effect, payload, _o=orig_apply: _o(self, {**effect, "envelope_text": effect["envelope_text"] + "Writer: w1\n"}, payload)
        try:
            d = new_driver("project", "std")
            scn = next(s for s in ALL["project"] if s.id == "p_ok_create")
            d.engine.propose(scn.action, scn.inputs, scn.principal, idempotency_key="prov-1")
        finally:
            gf.GitFake.apply = orig_apply
    return t.provenance_numbers()


def git_adapter_run(tracer_cls, tamper: bool = False) -> dict:
    """One real GitAdapter / GitStore action (temp repo, never the real one). ``tamper`` plants an adapter subclass that appends
    its own 'Writer: w1' line to the commit message."""
    import subprocess
    import tempfile
    from pathlib import Path

    from eoo_exp.util import ROOT
    from eoo_engine_git import adapter as ga
    from eoo_h18.rig import EooRig, PRINCIPAL
    from domains.project.logic.freeze import git_blob_reader
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    ev = "exp-h15-002/real-domain-roundtrip.json"
    t = tracer_cls()
    orig_apply = ga.GitAdapter.apply
    with tempfile.TemporaryDirectory() as td, t.installed():
        if tamper:
            def evil(self, effect, payload, _o=orig_apply):
                return _o(self, {**effect, "envelope_text": effect["envelope_text"] + "Writer: w1\n"}, payload)
            ga.GitAdapter.apply = evil
        try:
            rig = EooRig(Path(td), reader=git_blob_reader(head), h15_state="RUNNING")
            rig.store.import_ops(rig.base_ops, source="t", ref="refs/heads/main", parent=rig.root)
            rig.engine("refs/heads/main").propose("attach_evidence", {"hypothesis": "H15", "evidence": ev}, PRINCIPAL, idempotency_key="a")
        finally:
            ga.GitAdapter.apply = orig_apply
    return t.provenance_numbers()


def probes(tracer_cls) -> dict:
    """Known-positive (real adapters: >0 writes, 0 mismatches) and known-negative (own line appended: detected) for both stores."""
    pos = {"git_fake": _git_fake_run(tracer_cls, False), "git_adapter": git_adapter_run(tracer_cls, False)}
    neg = {"git_fake": _git_fake_run(tracer_cls, True), "git_adapter": git_adapter_run(tracer_cls, True)}
    return {"known_positive": pos, "known_negative": neg,
            "known_negative_detected": all(v["adapter_provenance_verbatim_mismatches"] > 0 for v in neg.values()),
            "known_positive_clean": all(v["adapter_provenance_verbatim_mismatches"] == 0 and v["adapter_provenance_writes"] > 0 for v in pos.values())}
