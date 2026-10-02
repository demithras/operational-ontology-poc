"""Canonical artifact layout: one versioned JSON file per object and per link. Pure functions, domain-blind.

    ontology/objects/<Type>/<key>.json     {"type": T, "key": k, "props": {...}}
    ontology/links/<Link>/<S>~<k>__<D>~<k>.json   {"type": L, "src": [T, k], "dst": [T, k], "props": {...}}

``artifact_digest`` is defined over the artifact bytes alone (no runtime state, no clock): the sha256 of
``path NUL bytes NUL`` for every file under ``ontology/`` in path order.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

ROOT = "ontology/"
_SAFE = re.compile(r"[A-Za-z0-9._@+-]")


def enc(key: Any) -> str:
    if isinstance(key, bool) or not isinstance(key, (str, int)):
        raise TypeError(f"key must be str or int, got {type(key).__name__}")
    if isinstance(key, int):
        return f"i~{key}"
    return "".join(c if _SAFE.fullmatch(c) else "".join(f"%{b:02X}" for b in c.encode()) for c in key) or "%00"


def obj_path(t: str, key: Any) -> str:
    return f"{ROOT}objects/{t}/{enc(key)}.json"


def link_path(lt: str, src, dst) -> str:
    return f"{ROOT}links/{lt}/{src[0]}~{enc(src[1])}__{dst[0]}~{enc(dst[1])}.json"


def dumps(rec: dict) -> bytes:
    return (json.dumps(rec, sort_keys=True, indent=1, ensure_ascii=True) + "\n").encode()


def obj_file(t: str, key: Any, props: dict) -> tuple[str, bytes]:
    return obj_path(t, key), dumps({"type": t, "key": key, "props": props})


def link_file(lt: str, src, dst, props: dict) -> tuple[str, bytes]:
    return link_path(lt, src, dst), dumps({"type": lt, "src": list(src), "dst": list(dst), "props": props})


def serialize(state) -> dict[str, bytes]:
    """Engine ``State`` (or anything with .objects / .links of the same shape) -> artifact files."""
    files = dict(obj_file(t, k, r["props"]) for (t, k), r in state.objects.items())
    files.update(link_file(lt, s, d, r["props"]) for (lt, s, d), r in state.links.items())
    return files


def to_ops(files: dict[str, bytes]) -> list[dict]:
    """Artifact files -> seed ops in a deterministic order (objects by type/key, then links)."""
    objs, lnks = [], []
    for path in sorted(p for p in files if p.startswith(ROOT)):
        rec = json.loads(files[path])
        if path.startswith(ROOT + "objects/"):
            objs.append((rec["type"], repr(rec["key"]), {"op": "create", "type": rec["type"], "key": rec["key"],
                                                       "props": rec["props"]}))
        elif path.startswith(ROOT + "links/"):
            lnks.append((rec["type"], repr(rec["src"]), repr(rec["dst"]),
                         {"op": "link", "type": rec["type"], "src": rec["src"], "dst": rec["dst"], "props": rec["props"]}))
    return [o[-1] for o in sorted(objs, key=lambda x: x[:2])] + [o[-1] for o in sorted(lnks, key=lambda x: x[:3])]


def artifact_digest(files: dict[str, bytes]) -> str:
    h = hashlib.sha256()
    for path in sorted(p for p in files if p.startswith(ROOT)):
        h.update(path.encode() + b"\0" + files[path] + b"\0")
    return h.hexdigest()
