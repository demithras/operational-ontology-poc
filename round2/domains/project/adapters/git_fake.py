"""In-memory ``git_change`` adapter: a tiny commit log + tree. Translates an approved effect into one commit, returns
the raw response (commit sha + the row as stored) and emits GitCommitObserved observations.

Allowlist (protocol/ENGINE_PREREG.json H20): translate, answer, observe. No authority, policy, precondition,
idempotency decision, provenance or lifecycle logic here. Like Git itself it is content-addressed: re-applying the
same effect (same id, target and row) returns the same commit and never writes twice; an effect id reused with a
different row (a rebuilt Engine restarts its execution counter) is a new commit.

Fault modes (``git.mode``): ok | corrupt (the stored row differs from the payload: Git "holds something else") |
timeout (raises before committing). ``git.observe = False`` hides commit observations (lag).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Iterable


class GitUnavailable(TimeoutError):
    pass


class GitFake:
    def __init__(self, head: str = "0" * 40, clock: Callable[[], str] = lambda: "2026-10-02T00:00:00+00:00"):
        self.commits: list[dict] = []
        self.rows: dict[tuple, dict] = {}  # (target, key) -> merged row
        self.links: set[tuple] = set()  # (target, src, dst)
        self.head = head
        self.mode = "ok"
        self.observe = True
        self._clock = clock
        self._by_effect: dict[str, dict] = {}
        self.calls: list[dict] = []

    def apply(self, effect: Any, payload: Any) -> dict:
        eid = effect["effect_id"]
        self.calls.append({"effect_id": eid, "target": effect["target"], "payload": dict(payload)})
        ident = json.dumps([eid, effect["target"], dict(payload)], sort_keys=True, default=str)
        if ident in self._by_effect:
            return dict(self._by_effect[ident]["response"])
        if self.mode == "timeout":
            raise GitUnavailable("git backend did not answer")
        row = {k: v for k, v in dict(payload).items()}
        if self.mode == "corrupt":
            for k in ("value", "phase", "orphan_flagged"):
                if k in row:
                    row[k] = "TAMPERED" if isinstance(row[k], str) else (not row[k])
        sha = hashlib.sha1(json.dumps([self.head, eid, effect["target"], row], sort_keys=True, default=str).encode()).hexdigest()
        if "$src" in row:
            self.links.add((effect["target"], row["$src"], row["$dst"]))
        else:
            key = row.get("$key", row.get("id"))
            self.rows.setdefault((effect["target"], key), {}).update({k: v for k, v in row.items() if k != "$key"})
        commit = {"sha": sha, "parent": self.head, "effect_id": eid, "execution": effect["execution"],
                  "target": effect["target"], "row": row, "committed_at": self._clock()}
        self.commits.append(commit)
        self.head = sha
        response = {"commit": sha, "parent": commit["parent"], "target": effect["target"], "row": row}
        self._by_effect[ident] = {"response": response}
        return dict(response)

    def observations(self) -> Iterable[dict]:
        if not self.observe:
            return []
        return [{"observation_type": "GitCommitObserved", "execution": c["execution"],
                 "data": {"sha": c["sha"], "committed_at": c["committed_at"]}} for c in self.commits]
