"""File-level three-way merge of canonical artifacts (domain-blind).

``merge(base, ours, theirs)``: ``ours`` = base + the writer's change, ``theirs`` = the current head. The result is the
head with the writer's change replayed on it. A path changed by both sides is merged per JSON property of an object
file; two different values for the same property (or two different link files) is an explicit conflict record, never
a silent winner.
"""
from __future__ import annotations

import json

MISSING = object()


def changed_paths(base: dict, other: dict) -> list[str]:
    return sorted(p for p in set(base) | set(other) if base.get(p) != other.get(p))


def _props(blob):
    return MISSING if blob is None else json.loads(blob).get("props", {})


def merge_object(path: str, base: bytes | None, ours: bytes, theirs: bytes) -> tuple[bytes | None, list[dict]]:
    from .layout import dumps
    b, o, t = _props(base), _props(ours), _props(theirs)
    b = {} if b is MISSING else b
    out, conflicts = {}, []
    for k in sorted(set(b) | set(o) | set(t)):
        bv, ov, tv = b.get(k, MISSING), o.get(k, MISSING), t.get(k, MISSING)
        if ov == tv or tv == bv:
            pick = ov
        elif ov == bv:
            pick = tv
        else:
            conflicts.append({"path": path, "kind": "property", "property": k, "base": None if bv is MISSING else bv,
                              "ours": None if ov is MISSING else ov, "theirs": None if tv is MISSING else tv})
            continue
        if pick is not MISSING:
            out[k] = pick
    if conflicts:
        return None, conflicts
    rec = json.loads(ours)
    rec["props"] = out
    return dumps(rec), []


def merge(base: dict, ours: dict, theirs: dict) -> tuple[dict, list[dict], list[str]]:
    """(merged files, conflicts, paths merged property-wise)."""
    merged, conflicts, joint = dict(theirs), [], []
    their = set(changed_paths(base, theirs))
    for path in changed_paths(base, ours):
        mine = ours.get(path)
        if path not in their or theirs.get(path) == mine:
            if mine is None:
                merged.pop(path, None)
            else:
                merged[path] = mine
            continue
        if mine is not None and theirs.get(path) is not None and "/objects/" in path:
            blob, cs = merge_object(path, base.get(path), mine, theirs[path])
            if not cs:
                merged[path] = blob
                joint.append(path)
                continue
            conflicts += cs
            continue
        conflicts.append({"path": path, "kind": "file", "base": None if base.get(path) is None else base[path].decode(),
                          "ours": None if mine is None else mine.decode(),
                          "theirs": None if theirs.get(path) is None else theirs[path].decode()})
    return merged, conflicts, joint
