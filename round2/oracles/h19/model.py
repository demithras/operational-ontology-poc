"""H19 oracle: an immutable commit DAG over logical ontology state plus a deterministic projection hash.

Pure Python, no imports from the Engine, the Git store or any domain logic, and it never reads a repository: the harness feeds
it the logical state it extracted from Git (``entry -> props``) and the writes it attempted. It answers, for every write:
what the canonical outcome must be (accepted with this exact state, an explicit property conflict, or a rejection).

Logical state: ``{entry: props}`` with ``entry`` = ``obj|<Type>|<key>`` or ``lnk|<Link>|<SrcType>|<srcKey>|<DstType>|<dstKey>``.
A change is a list of ``{"e": entry, "props": {...}}`` applied in order: an unseen entry is created with ``props``, a seen one gets
its properties overwritten. Immutable properties of an existing entry may not change. A link needs both endpoints.
"""
from __future__ import annotations

import copy
import hashlib
import json

MISSING = object()
# properties that may never change once the object exists (contract of the Project ontology: bindings are pinned)
IMMUTABLE = {"Evidence": ("payload_hash", "git_commit", "experiment_version", "environment"),
             "Verdict": ("value", "derivation_hash", "git_commit")}


def canon(x) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def state_hash(state: dict) -> str:
    """Deterministic projection digest: a function of the logical state alone (no clock, no ids, no insertion order)."""
    return hashlib.sha256(canon({e: state[e] for e in sorted(state)}).encode()).hexdigest()


def obj(t: str, key: str) -> str:
    return f"obj|{t}|{key}"


def lnk(t: str, src: tuple, dst: tuple) -> str:
    return f"lnk|{t}|{src[0]}|{src[1]}|{dst[0]}|{dst[1]}"


def endpoints(entry: str) -> list[str]:
    p = entry.split("|")
    return [obj(p[2], p[3]), obj(p[4], p[5])] if p[0] == "lnk" else []


def etype(entry: str) -> str:
    return entry.split("|")[1]


def apply_change(base: dict, change: list) -> tuple[dict, list]:
    """(state after the change, problems). Problems make the whole write a rejection (nothing is written)."""
    out, problems = copy.deepcopy(base), []
    for ch in change:
        e, props = ch["e"], ch.get("props", {})
        if e.startswith("lnk|"):
            miss = [x for x in endpoints(e) if x not in out]
            if miss:
                problems.append(f"{e}: endpoint {miss[0]} does not exist")
            elif e not in out:
                out[e] = {}
            continue
        if e in out:
            bad = [p for p in IMMUTABLE.get(etype(e), ()) if p in props and props[p] != out[e].get(p)]
            if bad:
                problems.append(f"{e}: immutable {bad[0]}")
                continue
            out[e] = {**out[e], **props}
        else:
            out[e] = {"id": e.split("|")[2], **props}  # the object key is also its ``id`` property in the canonical record
    return out, problems


def three_way(base: dict, ours: dict, head: dict) -> tuple[dict, list]:
    """Replay the writer's change (``ours`` = base + change) on ``head``. Returns (merged state, conflicts [(entry, prop)])."""
    merged, conflicts = copy.deepcopy(head), []
    for e in sorted(set(base) | set(ours)):
        if ours.get(e) == base.get(e):
            continue  # the writer did not touch this entry
        o, b, t = ours[e], base.get(e), head.get(e)
        if t == b:
            merged[e] = copy.deepcopy(o)  # nobody else touched it
            continue
        if t == o:
            continue  # someone made the identical change
        b, t = b or {}, t or {}
        res = {}
        for p in sorted(set(b) | set(o) | set(t)):
            bv, ov, tv = b.get(p, MISSING), o.get(p, MISSING), t.get(p, MISSING)
            if ov == tv or tv == bv:
                pick = ov
            elif ov == bv:
                pick = tv
            else:
                conflicts.append((e, p))
                continue
            if pick is not MISSING:
                res[p] = pick
        if not conflicts:
            merged[e] = res
    return (merged if not conflicts else head), sorted(conflicts)


class Outcome:
    def __init__(self, kind: str, state=None, conflicts=(), problems=(), classes=()):
        self.kind, self.state, self.conflicts, self.problems, self.classes = kind, state, list(conflicts), list(problems), list(classes)
        self.hash = state_hash(state) if state is not None else None


class Dag:
    """Immutable commit DAG of one branch. Commit ``i`` is never changed after it is added; ``write`` appends or refuses."""

    def __init__(self, root_state: dict):
        self.commits: list[tuple[tuple, dict]] = [((), copy.deepcopy(root_state))]

    @property
    def head(self) -> int:
        return len(self.commits) - 1

    def state(self, i: int) -> dict:
        return self.commits[i][1]

    def hash(self, i: int) -> str:
        return state_hash(self.commits[i][1])

    def write(self, base: int, change: list, mode: str = "compatible") -> Outcome:
        """The canonical outcome of a write that was prepared on commit ``base`` while the branch head is ``self.head``."""
        stale = base != self.head
        ours, problems = apply_change(self.state(base), change)
        if problems:
            return Outcome("rejected", problems=problems, classes=["stale_base"] if stale else [])
        if not stale:
            self.commits.append(((self.head,), ours))
            return Outcome("ok", ours, classes=[])
        if mode == "never":
            return Outcome("conflict", conflicts=[("*", "stale_base")], classes=["stale_base", "stale_refused"])
        merged, conflicts = three_way(self.state(base), ours, self.state(self.head))
        if conflicts:
            return Outcome("conflict", conflicts=conflicts, classes=["stale_base", "conflicting_concurrent"])
        self.commits.append(((self.head,), merged))
        return Outcome("ok", merged, classes=["stale_base", "compatible_concurrent"])
