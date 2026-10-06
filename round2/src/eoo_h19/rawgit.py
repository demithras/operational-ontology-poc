"""Read a commit's logical ontology state straight from Git with the ``git`` CLI (not through GitStore): the oracle's input.

``logical(sha)`` -> {entry: props} in the oracle's entry notation, parsed from the JSON files under ``ontology/`` of the commit.
Blobs come through one long-lived ``git cat-file --batch``; results are cached per commit (commits are immutable).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


class RawGit:
    def __init__(self, path):
        self.path = str(Path(path))
        self._cat = subprocess.Popen(["git", "-C", self.path, "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        self._blobs: dict[str, tuple[str, bytes]] = {}
        self._logical: dict[str, dict] = {}

    def close(self) -> None:
        try:
            self._cat.stdin.close()
            self._cat.wait(timeout=10)
        except Exception:  # noqa: BLE001
            self._cat.kill()

    def git(self, *args: str) -> str:
        r = subprocess.run(["git", "-C", self.path, *args], capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()[:200]}")
        return r.stdout

    def obj(self, sha: str) -> tuple[str, bytes]:
        if sha not in self._blobs:
            self._cat.stdin.write(sha.encode() + b"\n")
            self._cat.stdin.flush()
            _, kind, size = self._cat.stdout.readline().split()
            data = self._cat.stdout.read(int(size))
            self._cat.stdout.read(1)
            self._blobs[sha] = (kind.decode(), data)
        return self._blobs[sha]

    def blob(self, sha: str) -> bytes:
        kind, data = self.obj(sha)
        assert kind == "blob", kind
        return data

    def commit(self, sha: str) -> dict:
        kind, data = self.obj(sha)
        assert kind == "commit", kind
        head, _, msg = data.decode().partition("\n\n")
        rec = {"parents": [], "message": msg}
        for ln in head.split("\n"):
            k, _, v = ln.partition(" ")
            if k == "tree":
                rec["tree"] = v
            elif k == "parent":
                rec["parents"].append(v)
        return rec

    def files(self, tree: str, prefix: str = "") -> dict:
        """{path: blob sha} of a tree, from raw Git tree objects (cached per tree sha)."""
        key = f"T{tree}{prefix}"
        if key not in self._logical:
            kind, data = self.obj(tree)
            assert kind == "tree", kind
            out, i = {}, 0
            while i < len(data):
                j = data.index(b"\0", i)
                mode, name = data[i:j].decode().split(" ", 1)
                sub = data[j + 1:j + 21].hex()
                if mode == "40000":
                    out.update(self.files(sub, prefix + name + "/"))
                else:
                    out[prefix + name] = sub
                i = j + 21
            self._logical[key] = out
        return self._logical[key]

    def logical(self, sha: str) -> dict:
        if sha not in self._logical:
            out = {}
            for path, bsha in self.files(self.commit(sha)["tree"]).items():
                if not path.startswith("ontology/"):
                    continue
                rec = json.loads(self.blob(bsha))
                if path.startswith("ontology/objects/"):
                    out[f"obj|{rec['type']}|{rec['key']}"] = rec["props"]
                else:
                    out[f"lnk|{rec['type']}|{rec['src'][0]}|{rec['src'][1]}|{rec['dst'][0]}|{rec['dst'][1]}"] = rec["props"]
            self._logical[sha] = out
        return self._logical[sha]

    def head(self, ref: str) -> str | None:
        p = Path(self.path) / ".git" / ref
        if p.exists():
            return p.read_text().strip()
        r = subprocess.run(["git", "-C", self.path, "rev-parse", "--verify", "--quiet", ref], capture_output=True, text=True, timeout=60)
        return r.stdout.strip() or None

    def count(self, rev: str) -> int:
        return int(self.git("rev-list", "--count", rev).strip())

    def parents(self, sha: str) -> list[str]:
        return self.commit(sha)["parents"]

    def message(self, sha: str) -> str:
        return self.commit(sha)["message"]

    def all_commits(self) -> list[str]:
        return self.git("rev-list", "--all", "--reverse").split()

    def fsck(self) -> bool:
        return subprocess.run(["git", "-C", self.path, "fsck", "--strict"], capture_output=True, timeout=600).returncode == 0
