"""Minimal Git object database written in pure Python (loose objects only), compatible with the real ``git`` CLI.

Why not shell out: a generated-corpus run makes tens of thousands of commits; one ``git`` subprocess per object is
too slow and non-deterministic in its timestamps. The repository is an ordinary Git repository (``git init`` makes
it; ``git fsck --strict`` / ``git log`` read it): this module only writes blob / tree / commit objects and refs.
Domain-blind: bytes in, bytes out.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import zlib
from pathlib import Path
from typing import Optional

AUTHOR = "EOO Store <eoo-store@invalid>"


def _sha(kind: str, data: bytes) -> tuple[str, bytes]:
    raw = f"{kind} {len(data)}".encode() + b"\0" + data
    return hashlib.sha1(raw).hexdigest(), raw


class Repo:
    """A real Git repository directory. ``write_*`` are idempotent (content-addressed)."""

    def __init__(self, path):
        self.path = Path(path)
        self._git = self.path / ".git"
        self._cache: dict[str, tuple[str, bytes]] = {}

    @classmethod
    def init(cls, path) -> "Repo":
        Path(path).mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", "--initial-branch=main", str(path)], check=True, capture_output=True, timeout=60)
        return cls(path)

    # ---- objects --------------------------------------------------------------------------
    def _put(self, kind: str, data: bytes) -> str:
        sha, raw = _sha(kind, data)
        p = self._git / "objects" / sha[:2] / sha[2:]
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_bytes(zlib.compress(raw, 1))
            os.replace(tmp, p)
        self._cache[sha] = (kind, data)
        return sha

    def write_blob(self, data: bytes) -> str:
        return self._put("blob", data)

    def write_tree(self, entries: dict[str, tuple[str, str]]) -> str:
        """entries: name -> (mode, sha); mode '100644' (file) or '40000' (tree). Git's own entry order."""
        out = b""
        for name in sorted(entries, key=lambda n: n + "/" if entries[n][0] == "40000" else n):
            mode, sha = entries[name]
            out += f"{mode} {name}".encode() + b"\0" + bytes.fromhex(sha)
        return self._put("tree", out)

    def write_commit(self, tree: str, parents: list[str], message: str, epoch: int) -> str:
        lines = [f"tree {tree}"] + [f"parent {p}" for p in parents]
        lines += [f"author {AUTHOR} {epoch} +0000", f"committer {AUTHOR} {epoch} +0000", "", message]
        return self._put("commit", ("\n".join(lines) + ("" if message.endswith("\n") else "\n")).encode())

    def read(self, sha: str) -> tuple[str, bytes]:
        if sha in self._cache:
            return self._cache[sha]
        p = self._git / "objects" / sha[:2] / sha[2:]
        if not p.exists():
            raise KeyError(f"object {sha} not found")
        raw = zlib.decompress(p.read_bytes())
        head, _, data = raw.partition(b"\0")
        got = (head.split()[0].decode(), data)
        self._cache[sha] = got
        return got

    def read_tree(self, sha: str) -> dict[str, tuple[str, str]]:
        kind, data = self.read(sha)
        assert kind == "tree", kind
        out, i = {}, 0
        while i < len(data):
            j = data.index(b"\0", i)
            mode, name = data[i:j].decode().split(" ", 1)
            out[name] = (mode, data[j + 1:j + 21].hex())
            i = j + 21
        return out

    def read_commit(self, sha: str) -> dict:
        kind, data = self.read(sha)
        assert kind == "commit", kind
        head, _, message = data.decode().partition("\n\n")
        rec = {"parents": [], "message": message}
        for ln in head.split("\n"):
            k, _, v = ln.partition(" ")
            if k == "parent":
                rec["parents"].append(v)
            elif k in ("tree", "author", "committer"):
                rec[k] = v
        return rec

    # ---- refs -----------------------------------------------------------------------------
    def set_ref(self, ref: str, sha: str) -> None:
        p = self._git / ref
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(sha + "\n")
        os.replace(tmp, p)

    def get_ref(self, ref: str) -> Optional[str]:
        p = self._git / ref
        return p.read_text().strip() if p.exists() else None

    def has(self, sha: str) -> bool:
        return (self._git / "objects" / sha[:2] / sha[2:]).exists()
