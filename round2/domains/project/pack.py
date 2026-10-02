"""The only thing the Engine is given for the Project Ontology: (LogicBindings, adapters, seed).

Two configurations of the same logic: the in-memory ``git_fake`` adapter (P4b, ``git=``) or the real Git-backed store
(H18/H19, ``store=``: canonical state is the projection of a commit of a Git repository and every governed Action is
one commit). ``evaluators`` registers extra experiment evaluators by ``Experiment.evaluator_ref``.
"""
from __future__ import annotations

from domains._pack import load_ir

from .adapters.git_fake import GitFake
from .evaluators import h15_evaluator
from .logic import build_bindings
from .logic.freeze import git_blob_reader
from .seed_from_repo import H15_EVALUATOR, build_seed, principals


def build_pack(seed: dict | None = None, reader=None, git: GitFake | None = None, ir_version: str | None = None, *,
               store=None, writer: str = "w1", base: str | None = None, evaluators: dict | None = None,
               merge_mode: str = "compatible", mutate=None, ref: str | None = None, ir: dict | None = None, extend=None):
    """``mutate(bindings)`` (mutation proof only) may override built bindings; ``ir`` replaces the package (an extended
    contract, H18 task TC2/TC3) and ``extend(bindings)`` binds the logic its additions need. Both run before the store wrap."""
    reader = reader or git_blob_reader()
    ir = ir if ir is not None else load_ir("project", ir_version)
    adapter = None
    if store is not None:
        from eoo_engine_git import GitAdapter
        from eoo_engine_git.store import MAIN
        adapter = GitAdapter(store, writer, base=base, ref=ref or MAIN, merge_mode=merge_mode)
        seed = {"description": f"projection of Git commit {adapter.base}", "head_commit": adapter.base,
                "principals": principals(), "ops": store.seed_ops_at(adapter.base)}
    else:
        seed = seed if seed is not None else build_seed(reader)
        git = git or GitFake(head=seed.get("head_commit", "0" * 40))
    bindings = build_bindings(ir, {H15_EVALUATOR: h15_evaluator(reader), **(evaluators or {})}, reader)
    for hook in (extend, mutate):
        if hook is not None:
            hook(bindings)
    if adapter is not None:
        from eoo_engine_git import attach
        attach(bindings, ir, adapter)
    return bindings, {("git_change", "*"): adapter if adapter is not None else git}, seed
