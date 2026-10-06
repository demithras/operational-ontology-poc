"""Shared helpers for the Project Ontology end-to-end tests."""
from __future__ import annotations

import copy
import functools

from domains._pack import boot, load_ir
from domains.project.adapters.git_fake import GitFake
from domains.project.pack import build_pack
from domains.project.projection import project
from domains.project.seed_from_repo import H15_EVIDENCE_FILES, build_seed

NOW = "2026-10-02T12:00:00+00:00"


@functools.lru_cache(maxsize=None)
def base_seed(state: str = "EVALUATED") -> dict:
    return build_seed(h15_state=state)


def seed(state: str = "EVALUATED", mutator=None) -> dict:
    s = copy.deepcopy(base_seed(state))
    if mutator:
        mutator(s)
    return s


def prop(s: dict, typ: str, key, **changes):
    """Mutate the props of one seed object in place (test-only fixture surgery)."""
    for o in s["ops"]:
        if o["op"] == "create" and o["type"] == typ and o["key"] == key:
            o["props"].update(changes)
            for k in [k for k, v in changes.items() if v is None]:
                del o["props"][k]
            return o
    raise KeyError((typ, key))


def drop_link(s: dict, typ: str, src, dst=None):
    before = len(s["ops"])
    s["ops"] = [o for o in s["ops"] if not (o["op"] == "link" and o["type"] == typ and o["src"][1] == src
                                             and (dst is None or o["dst"][1] == dst))]
    assert len(s["ops"]) < before, (typ, src, dst)


def make(state="EVALUATED", mutator=None, sd=None, package=None, ir_version=None):
    """(engine, git, pack, seed) booted from a seed variant; the Git fake starts empty at the seed's head commit.
    ``package`` overrides the IR (tests only: isolate one policy by removing the preconditions in front of it)."""
    sd = sd if sd is not None else seed(state, mutator)
    git = GitFake(head=sd["head_commit"], clock=lambda: NOW)
    pack = build_pack(sd, git=git, ir_version=ir_version)
    pkg = package if package is not None else (load_ir("project", ir_version) if ir_version else None)
    return boot("project", pack, clock=lambda: NOW, package=pkg), git, pack, sd


def ir_without_preconditions(action_id: str) -> dict:
    ir = copy.deepcopy(load_ir("project"))
    for a in ir["actions"]:
        if a["id"] == action_id:
            a["preconditions"] = []
    return ir


def next_engine(base_seed_, git, ir_version=None):
    """Rebuild the projection from Git (base seed + every commit so far) and boot a fresh Engine on it; the same Git
    fake keeps its history."""
    sd2 = project(base_seed_, git)
    pack = build_pack(sd2, git=git, ir_version=ir_version)
    return boot("project", pack, clock=lambda: NOW, package=load_ir("project", ir_version) if ir_version else None)


class Snap:
    def __init__(self, e, git):
        self.e, self.git = e, git
        self.state, self.effects, self.commits = e.state().state_hash(), len(e.effect_log.entries()), len(git.commits)

    def unchanged(self) -> bool:
        return (self.e.state().state_hash(), len(self.e.effect_log.entries()), len(self.git.commits)) == \
            (self.state, self.effects, self.commits)


def gate(rec, name):
    return next((g for g in rec["gates"] if g["gate"] == name), None)


def failed_gates(rec):
    return [g["gate"] for g in rec["gates"] if not g["passed"]]


EVIDENCE_002 = [f"exp-h15-002/{n}" for n in H15_EVIDENCE_FILES]
