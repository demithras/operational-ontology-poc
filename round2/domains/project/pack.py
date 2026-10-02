"""The only thing the Engine is given for the Project Ontology: (LogicBindings, adapters, seed)."""
from __future__ import annotations

from domains._pack import load_ir

from .adapters.git_fake import GitFake
from .evaluators import h15_evaluator
from .logic import build_bindings
from .logic.freeze import git_blob_reader
from .seed_from_repo import H15_EVALUATOR, build_seed


def build_pack(seed: dict | None = None, reader=None, git: GitFake | None = None, ir_version: str | None = None):
    reader = reader or git_blob_reader()
    seed = seed if seed is not None else build_seed(reader)
    git = git or GitFake(head=seed.get("head_commit", "0" * 40))
    bindings = build_bindings(load_ir("project", ir_version), {H15_EVALUATOR: h15_evaluator(reader)}, reader)
    return bindings, {("git_change", "*"): git}, seed
