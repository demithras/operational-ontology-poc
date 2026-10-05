"""The small Project-ontology seed the concurrency corpus starts from, and conversions between oracle changes and store rows."""
from __future__ import annotations

import tempfile
from pathlib import Path

from domains._pack import load_ir
from eoo_engine import ENGINE_VERSION
from eoo_engine_git import GitStore

from .oracle import M

T0 = "2026-10-05T00:00:00+00:00"


def _o(t: str, key: str, **props) -> dict:
    return {"op": "create", "type": t, "key": key, "props": {"id": key, **props}}


def seed_ops() -> list:
    ops = [_o("Hypothesis", f"h{i}", claim=f"claim-{i}", phase="DRAFT") for i in (1, 2, 3)]
    ops += [_o("Threshold", f"t{i}", value=i) for i in (1, 2, 3, 4)]
    ops += [_o("Metric", f"m{i}", name=f"metric-{i}") for i in (1, 2, 3)]
    ops += [_o("Component", f"c{i}", path=f"src/c{i}.py", orphan_flagged=False) for i in (1, 2, 3)]
    ops += [_o("Experiment", "e1", version="1", evidence_schema_ref="schema-1", evaluator_ref="eval-1")]
    ops += [{"op": "link", "type": "GOVERNED_BY", "src": ["Metric", "m1"], "dst": ["Threshold", "t1"], "props": {}},
            {"op": "link", "type": "EXISTS_FOR", "src": ["Component", "c1"], "dst": ["Hypothesis", "h1"], "props": {}}]
    return ops


def change_to_rows(change: list) -> list:
    """Oracle change -> GitStore rows [(target, row)]."""
    rows = []
    for ch in change:
        p = ch["e"].split("|")
        if p[0] == "obj":
            rows.append((p[1], {"id": p[2], **ch.get("props", {})}))
        else:
            rows.append((p[1], {"$src": p[3], "$dst": p[5]}))
    return rows


def conflict_pairs(conflicts: list) -> list:
    """Store conflict records -> [(oracle entry, property)] (property conflicts only; a stale-base refusal is ('*', 'stale_base'))."""
    out = []
    for c in conflicts:
        if c["kind"] == "stale_base":
            out.append(("*", "stale_base"))
        elif c["kind"] == "property":
            t, f = c["path"].split("/")[-2], c["path"].split("/")[-1][:-5]
            out.append((f"obj|{t}|{f}", c["property"]))
        else:
            out.append((c["path"], c["kind"]))
    return sorted(out)


class Env:
    """One temporary Git repository holding the seed commit; scenarios branch off it (one ref each)."""

    def __init__(self, workdir=None, *, ir_version=None, clock=None):
        from .rawgit import RawGit
        self.workdir = Path(workdir or tempfile.mkdtemp(prefix="eoo-h19-"))
        self.package = load_ir("project", ir_version)
        self.tick = 0
        self.store = GitStore.init(self.workdir / "repo", self.package, engine_version=ENGINE_VERSION, clock=clock or self._clock)
        self.root = self.store.import_ops(seed_ops(), source="h19-seed")
        self.raw = RawGit(self.workdir / "repo")
        self.root_state = self.raw.logical(self.root)

    def _clock(self) -> str:
        import datetime as dt
        self.tick += 1
        return (dt.datetime(2026, 10, 5, tzinfo=dt.timezone.utc) + dt.timedelta(seconds=self.tick)).isoformat()

    def close(self) -> None:
        self.raw.close()
        self.store.repo._cache.clear()
