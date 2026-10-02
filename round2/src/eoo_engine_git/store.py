"""GitStore: canonical state = deterministic projection of the artifact files at a Git commit.

* ``import_ops`` / ``put_files`` write a commit (validated by the Engine's generic integrity rules first).
* ``commit_rows`` is the only durable write path for governed changes: ONE commit per call, carrying execution id,
  base commit and provenance trailers; optimistic concurrency on the writer's ``base``.
* ``state_at`` / ``seed_at`` / ``files_at`` / ``canonical_hash`` rebuild from a commit alone (pure; no clock, no runtime state).
"""
from __future__ import annotations

import datetime as _dt
from collections import OrderedDict
from pathlib import Path
from typing import Callable, Optional

from eoo_engine.canon import to_plain
from eoo_engine.registry import load_model
from eoo_engine.state import State
from eoo_engine.store import would_be

from . import layout
from .errors import ConflictError, RowRejected, StoreError
from .merge import merge
from .objects import Repo

MAIN = "refs/heads/main"
RESERVED = ("$key", "$src", "$dst")


def _epoch(clock: Callable[[], str]) -> int:
    return int(_dt.datetime.fromisoformat(clock()).timestamp())


class GitStore:
    def __init__(self, repo: Repo, package: dict, *, engine_version: str, clock: Callable[[], str], provenance: bool = True):
        self.repo, self.package, self.engine_version, self.clock = repo, package, engine_version, clock
        self.provenance = provenance
        # the observation type this package declares for Git (source_binding == "git"); None -> the store emits no observations
        self.obs_type = next((o["id"] for o in package.get("observation_types", []) if o.get("source_binding") == "git"), None)
        self.model = load_model(package)
        self.n_git = {a["id"]: sum(1 for e in a["effects"] if e["operation"] == "git_change") for a in package["actions"]}
        self.log: list[dict] = []  # every commit this store made through commit_rows (replayable record)
        self.conflicts: list[dict] = []  # every refused concurrent write
        self._snap: dict[str, dict] = {}
        self._lru_files, self._lru_state = OrderedDict(), OrderedDict()

    @classmethod
    def init(cls, path, package: dict, **kw) -> "GitStore":
        return cls(Repo.init(path), package, **kw)

    # ---- reading (a pure function of the commit) ------------------------------------------
    def head(self, ref: str = MAIN) -> Optional[str]:
        return self.repo.get_ref(ref)

    def _snapshot(self, sha: str) -> dict:
        if sha not in self._snap:
            snap: dict = {}

            def walk(tree, prefix):
                for name, (mode, s) in self.repo.read_tree(tree).items():
                    walk(s, prefix + name + "/") if mode == "40000" else snap.__setitem__(prefix + name, s)
            walk(self.repo.read_commit(sha)["tree"], "")
            self._snap[sha] = snap
        return self._snap[sha]

    def _lru(self, cache: OrderedDict, key, make):
        if key in cache:
            cache.move_to_end(key)
            return cache[key]
        cache[key] = make()
        if len(cache) > 48:
            cache.popitem(last=False)
        return cache[key]

    def files_at(self, sha: str) -> dict[str, bytes]:
        return dict(self._lru(self._lru_files, sha, lambda: {p: self.repo.read(b)[1] for p, b in self._snapshot(sha).items()}))

    def state_at(self, sha: str) -> State:
        def build():
            st, errs = would_be(State(self.model), layout.to_ops(self.files_at(sha)))
            if errs:
                raise StoreError(f"commit {sha[:10]} does not project to a valid state: {errs[:3]}")
            return st
        return self._lru(self._lru_state, sha, build)

    def seed_ops_at(self, sha: str) -> list[dict]:
        return layout.to_ops(self.files_at(sha))

    def canonical_hash(self, sha: str) -> str:
        return layout.artifact_digest(self.files_at(sha))

    def history(self, sha: Optional[str] = None) -> list[str]:
        """First-parent chain, newest first."""
        out, cur = [], sha or self.head()
        while cur:
            out.append(cur)
            ps = self.repo.read_commit(cur)["parents"]
            cur = ps[0] if ps else None
        return out

    # ---- writing --------------------------------------------------------------------------
    def _write_commit(self, files: dict, parent: Optional[str], message: str, ref: str) -> str:
        snap = {p: self.repo.write_blob(b) for p, b in files.items()}
        root: dict = {}
        for path, b in snap.items():
            d = root
            *dirs, leaf = path.split("/")
            for p in dirs:
                d = d.setdefault(p, {})
            d[leaf] = b

        def build(node):
            return self.repo.write_tree({n: ("40000", build(v)) if isinstance(v, dict) else ("100644", v)
                                         for n, v in node.items()})
        sha = self.repo.write_commit(build(root), [parent] if parent else [], message, _epoch(self.clock))
        self._snap[sha] = snap
        self.repo.set_ref(ref, sha)
        return sha

    def import_ops(self, ops: list, *, source: str, ref: str = MAIN, parent: Optional[str] = None, extra: dict | None = None) -> str:
        st, errs = would_be(State(self.model), to_plain(ops))
        if errs:
            raise RowRejected(errs)
        trailers = {"EOO-Import-Source": source, **(extra or {})}
        return self._write_commit(layout.serialize(st), parent, self._msg("import", trailers), ref)

    def put_files(self, files: dict, *, message: str, ref: str, parent: Optional[str]) -> str:
        """Commit an artifact snapshot (fixtures / test setup); it must project to a valid state."""
        _, errs = would_be(State(self.model), layout.to_ops(files))
        if errs:
            raise RowRejected(errs)
        return self._write_commit(files, parent, self._msg(message, {"EOO-Import-Source": "fixture"}), ref)

    def _msg(self, subject: str, trailers: dict) -> str:
        if not self.provenance:
            return subject + "\n"
        return subject + "\n\n" + "\n".join(f"{k}: {v}" for k, v in trailers.items()) + "\n"

    def rows_to_ops(self, st: State, rows: list) -> tuple[list, list[str]]:
        """Translate (target, row) pairs into store ops, validating on a running fork. Returns (ops, problems)."""
        ops, errs = [], []
        for target, row in rows:
            row = to_plain(row)
            props = {k: v for k, v in row.items() if not k.startswith("$")}
            ot, lt = self.model.get("object_types", target), self.model.get("link_types", target)
            if lt is not None and "$src" in row:
                ends = []
                for declared, k in ((lt.src, row.get("$src")), (lt.dst, row.get("$dst"))):
                    hits = st.locate(declared, k)
                    ends.append([hits[0][0], hits[0][1]] if len(hits) == 1 else None)
                if None in ends:
                    errs.append(f"{target}: endpoint {row.get('$src')!r}->{row.get('$dst')!r} does not resolve")
                    continue
                if (target, tuple(ends[0]), tuple(ends[1])) in st.links:
                    continue  # already present: idempotent
                op = {"op": "link", "type": target, "src": ends[0], "dst": ends[1], "props": props}
            elif ot is not None:
                key = row.get("$key", row.get(ot.pk))
                exists = (target, key) in st.objects
                if "$key" in row and not exists:
                    errs.append(f"{target}[{key!r}]: update of a missing object")
                    continue
                op = ({"op": "update", "type": target, "key": key, "props": props} if exists else
                      {"op": "create", "type": target, "key": key, "props": props})
            else:
                errs.append(f"{target!r} is neither an object type nor a link type of the package")
                continue
            st, e = would_be(st, [op])
            if e:
                errs += e
                continue
            ops.append(op)
        return ops, errs

    def commit_rows(self, *, rows: list, base: str, writer: str, meta: dict, ref: str = MAIN, merge_mode: str = "compatible") -> dict:
        head = self.head(ref)
        base_state = self.state_at(base)
        ops, errs = self.rows_to_ops(base_state, rows)
        if errs:
            raise RowRejected(errs)
        new_state, errs = would_be(base_state, ops)
        if errs:
            raise RowRejected(errs)
        base_files, ours = self.files_at(base), layout.serialize(new_state)
        how, files, joint = "none", ours, []
        if head != base:
            if merge_mode == "never":
                conf = [{"path": "*", "kind": "stale_base", "base": base, "ours": None, "theirs": head}]
                self.conflicts.append({"base": base, "head": head, "writer": writer, "meta": meta, "conflicts": conf})
                raise ConflictError(base, head, conf)
            files, conf, joint = merge(base_files, ours, self.files_at(head))
            if not conf:
                _, e = would_be(State(self.model), layout.to_ops(files))
                conf = [{"path": "*", "kind": "integrity", "base": None, "ours": None, "theirs": x} for x in e]
            if conf:
                self.conflicts.append({"base": base, "head": head, "writer": writer, "meta": meta, "conflicts": conf})
                raise ConflictError(base, head, conf)
            how = "compatible"
        trailers = {"EOO-Execution": meta["execution"], "EOO-Writer": writer, "EOO-Action": meta["action"],
                    "EOO-Idempotency-Key": meta.get("idempotency_key") or "-", "EOO-Effects": " ".join(meta["effects"]),
                    "EOO-Targets": ",".join(t for t, _ in rows), "EOO-Base": base, "EOO-Head-At-Write": head or "-",
                    "EOO-Merge": how, "EOO-Engine-Version": self.engine_version,
                    "EOO-Package": f"{self.model.package_id}@{self.model.version}",
                    "EOO-State-Hash": layout.artifact_digest(files)}
        sha = self._write_commit(files, head, self._msg(f"{meta['action']}: {meta['execution']}", trailers), ref)
        rec = {"sha": sha, "parent": head, "base": base, "merge": how, "joint_paths": joint, "writer": writer,
               "execution": meta["execution"], "action": meta["action"], "targets": [t for t, _ in rows]}
        self.log.append(rec)
        return rec
