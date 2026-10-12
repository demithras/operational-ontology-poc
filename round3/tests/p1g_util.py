"""Shared helpers for the P1g tests (r3_shared + fakes only)."""
import json
import os
import shutil
import tempfile
from pathlib import Path

from r3_shared.authsvc import start_authority
from r3_shared.clock import LogicalClock
from r3_shared.host import DeploymentProxy
from r3_shared.identity import IdentityProvider

ROUND3 = Path(__file__).resolve().parents[1]
FAKE = "tests.fakes.fake_g5:FakeG5Variant"
STALE = "tests.fakes.fake_g5:FakeStaleCacheVariant"
SECRET = "p1g-test-secret"
AUD = "fake"


def token(sub="alice", ttl=100000):
    return IdentityProvider(SECRET).issue(sub, AUD, ttl, LogicalClock(0))


class Rig:
    """One deployment's durable paths + optional AuthorityService; hosts are started/killed/resumed over the same paths."""

    def __init__(self, with_auth=True, anchor=None, history=False):
        self.root = Path(tempfile.mkdtemp(prefix="r3g"))
        self.work = self.root / "work"
        self.work.mkdir()
        (self.root / "ops.json").write_text("{}")
        self.auth = start_authority(self.root / "auth", self.root / "a.sock") if with_auth else None
        self.anchor, self.history = anchor, history
        self.hosts: list[DeploymentProxy] = []
        if with_auth:
            self.auth.control().publish(self.doc(0))

    @staticmethod
    def doc(n):
        return {"version": "t", "n": n}

    def spec(self, resume=False, root=None, dep_id="dep-g5", clock_start=0):
        r = Path(root or self.root)
        s = {"domain": "manufacturing", "ops_spec_path": str(self.root / "ops.json"), "auth_spec": self.doc(0),
             "world_path": str(r / "world.db"), "secret": SECRET, "clock_start": clock_start, "state_dir": None if self.history else str(r / "state"),
             "history_path": str(r / "hist.db") if self.history else None, "anchor_sock": self.anchor, "governance": None,
             "resume": resume, "deployment_id": dep_id, "authority": None, "external": None}
        if self.auth is not None:
            graph = ROUND3 / "spec" / "gate5" / "dependency-graph.json"
            s["authority"] = {"sock": self.auth.sock_path, "lease": 4, "graph_path": str(graph)}
        if not resume:
            (r / "state").mkdir(exist_ok=True)
            from r3_shared.world import WorldStore
            WorldStore(r / "world.db").reader().close()
        return s

    def start(self, variant=FAKE, resume=False, root=None, dep_id="dep-g5", tick=0, mutants=()):
        w = Path(root or self.root) / "work"
        w.mkdir(exist_ok=True)
        px = DeploymentProxy.start(variant, mutants, self.spec(resume, root, dep_id, tick), str(w), extra_paths=[str(ROUND3)])
        self.hosts.append(px)
        return px

    def reader(self, root=None):
        from r3_shared.world import WorldReader
        return WorldReader(str(Path(root or self.root) / "world.db"))

    def commits(self, root=None):
        r = self.reader(root)
        try:
            return [(x["data"]["request_id"]) for x in r.log() if x["kind"] == "mark" and x["ref"] == "commit"]
        finally:
            r.close()

    def cleanup(self):
        for h in self.hosts:
            try:
                h.close() if h.alive else None
            except Exception:
                pass
            if h.proc.poll() is None:
                h.kill()
        if self.auth is not None:
            try:
                self.auth.close()
            except Exception:
                self.auth.proc.kill()
        shutil.rmtree(self.root, ignore_errors=True)
