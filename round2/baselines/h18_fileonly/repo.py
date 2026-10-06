"""Shared plumbing: parse artifact files into a small model and write edits back."""
from __future__ import annotations

import json
import re

OBJ, LNK = "ontology/objects/", "ontology/links/"


class Model:
    def __init__(self, files: dict):
        self.objs, self.links = {}, set()
        for path, blob in files.items():
            rec = json.loads(blob)
            if path.startswith(OBJ):
                self.objs[(rec["type"], rec["key"])] = rec["props"]
            elif path.startswith(LNK):
                self.links.add((rec["type"], rec["src"][1], rec["dst"][1]))

    def props(self, t, k):
        return self.objs.get((t, k))

    def out(self, link, src):
        return sorted(d for (t, s, d) in self.links if t == link and s == src)

    def inn(self, link, dst):
        return sorted(s for (t, s, d) in self.links if t == link and d == dst)

    def keys(self, t):
        return sorted(k for (tt, k) in self.objs if tt == t)


def enc(v) -> str:
    return f"i~{v}" if isinstance(v, int) else "".join(c if re.fullmatch(r"[A-Za-z0-9._@+-]", c) else "".join(f"%{b:02X}" for b in c.encode()) for c in v) or "%00"


def set_object(files: dict, t: str, key, props: dict) -> dict:
    out = dict(files)
    path = f"{OBJ}{t}/{enc(key)}.json"
    cur = json.loads(files[path])["props"] if path in files else {}
    out[path] = (json.dumps({"type": t, "key": key, "props": {**cur, **props}}, sort_keys=True, indent=1) + "\n").encode()
    return out


def add_link(files: dict, t: str, src: tuple, dst: tuple) -> dict:
    out = dict(files)
    path = f"{LNK}{t}/{src[0]}~{enc(src[1])}__{dst[0]}~{enc(dst[1])}.json"
    out[path] = (json.dumps({"type": t, "src": list(src), "dst": list(dst), "props": {}}, sort_keys=True, indent=1) + "\n").encode()
    return out
