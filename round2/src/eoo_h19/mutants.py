"""H19 target mutations of the Git-backed store (applied by monkeypatch; each restores the original on exit)."""
from __future__ import annotations

import hashlib
from contextlib import contextmanager

import eoo_engine_git.store as S
from eoo_engine_git import GitStore


@contextmanager
def m1_timestamp_dependent_projection():
    """The canonical hash of a commit mixes in the clock at rebuild time."""
    orig = GitStore.canonical_hash
    GitStore.canonical_hash = lambda self, sha: hashlib.sha256((orig(self, sha) + self.clock()).encode()).hexdigest()
    try:
        yield
    finally:
        GitStore.canonical_hash = orig


@contextmanager
def m2_missing_base_version_check():
    """A stale write is applied as-is on the head (the writer's own snapshot wins): no base check, no merge, no conflict."""
    orig = S.merge
    S.merge = lambda base, ours, theirs: (ours, [], [])
    try:
        yield
    finally:
        S.merge = orig


@contextmanager
def m3_history_rebinding():
    """Resolving a pinned commit follows the latest commit the store wrote instead of the pin."""
    orig = GitStore.canonical_hash
    GitStore.canonical_hash = lambda self, sha: orig(self, self.log[-1]["sha"] if self.log else sha)
    try:
        yield
    finally:
        GitStore.canonical_hash = orig


@contextmanager
def m4_write_without_git_change():
    """(extra, Engine-level) the store reports a commit but the branch is put back: an accepted change that Git never shows."""
    orig = GitStore.commit_rows

    def commit_rows(self, **kw):
        rec = orig(self, **kw)
        self.repo.set_ref(kw.get("ref", S.MAIN), rec["parent"] or rec["sha"])
        return rec
    GitStore.commit_rows = commit_rows
    try:
        yield
    finally:
        GitStore.commit_rows = orig


@contextmanager
def m5_pinned_binding_rewritable():
    """(extra) the immutability rule of pinned evidence is off in the store: a later write may point evidence at a later commit."""
    orig = S.would_be

    def would_be(state, ops):
        st, errs = orig(state, ops)
        if errs and all("immutable" in e for e in errs):
            st = state.fork()
            for op in ops:
                if op["op"] == "update":
                    st.objects[(op["type"], op["key"])]["props"].update(op["props"])
                elif op["op"] == "create":
                    st.objects[(op["type"], op["key"])] = {"props": dict(op["props"])}
                else:
                    st.links[(op["type"], tuple(op["src"]), tuple(op["dst"]))] = {"props": dict(op.get("props", {}))}
            return st, []
        return st, errs
    S.would_be = would_be
    try:
        yield
    finally:
        S.would_be = orig


NULL = contextmanager(lambda: (yield))

# id, target (preregistered), context manager, the check that must go red, where it is exercised
REGISTRY = [
    {"id": "M1_timestamp_dependent_projection", "target": True, "ctx": m1_timestamp_dependent_projection, "expect": "rebuild_hash_equal", "level": "store"},
    {"id": "M2_missing_base_version_check", "target": True, "ctx": m2_missing_base_version_check, "expect": "no_lost_update", "level": "store"},
    {"id": "M3_history_rebinding", "target": True, "ctx": m3_history_rebinding, "expect": "binding_pinned", "level": "store"},
    {"id": "M5_pinned_binding_rewritable", "target": False, "ctx": m5_pinned_binding_rewritable, "expect": "no_rebinding_accepted", "level": "store"},
    {"id": "M4_write_without_git_change", "target": False, "ctx": m4_write_without_git_change, "expect": "canonical_change_traced", "level": "engine"},
]
