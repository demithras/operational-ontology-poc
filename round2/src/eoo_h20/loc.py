"""Contextual baseline: an explicit per-domain plugin architecture, measured with the numbers this repository can supply."""
from __future__ import annotations

import io
import tokenize
from pathlib import Path

from eoo_exp.util import ROOT


def loc(path: Path) -> int:
    """Non-blank, non-comment, non-docstring-only source lines (tokenizer based)."""
    lines = set()
    toks = list(tokenize.generate_tokens(io.StringIO(path.read_text()).readline))
    doc_lines = set()
    prev = None
    for t in toks:
        if t.type == tokenize.STRING and (prev is None or prev.type in (tokenize.NEWLINE, tokenize.INDENT, tokenize.NL, tokenize.DEDENT)):
            doc_lines.update(range(t.start[0], t.end[0] + 1))  # a bare string statement (docstring / comment-string)
        if t.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.COMMENT, tokenize.ENDMARKER):
            lines.update(range(t.start[0], t.end[0] + 1))
        prev = t
    return len(lines - doc_lines)


def dir_loc(rel: str, pattern: str = "*.py") -> dict:
    files = sorted((ROOT / rel).rglob(pattern))
    files = [f for f in files if "__pycache__" not in f.parts]
    return {"files": len(files), "loc": sum(loc(f) for f in files)}


def baseline(registered: dict, bindings_per_domain: dict) -> dict:
    """registered: {domain: {kind: [ids]}}; bindings_per_domain: {domain: number of bound callables}."""
    engine = dir_loc("src/eoo_engine")
    lifecycle = sum(loc(ROOT / "src/eoo_engine" / f) for f in ("pipeline.py", "gates.py", "authority.py", "effects.py", "outcome.py", "gatepass.py"))
    out = {"status": "CONTEXTUAL: derived from this repository's own numbers; no plugin implementation was written or measured",
           "generic_engine": {"engine_core": engine, "git_backed_store": dir_loc("src/eoo_engine_git"),
                              "lifecycle_modules_loc": lifecycle},
           "per_domain": {}}
    for dom, kinds in registered.items():
        logic = dir_loc(f"domains/{dom}/logic")
        adapters = dir_loc(f"domains/{dom}/adapters")
        ops = {k: len(v) for k, v in kinds.items()}
        # plugin rival: one handler per registered Action (carrying its own copy of the gate sequence) and one per Function / policy / authority rule
        handlers = sum(ops.get(k, 0) for k in ("actions", "functions", "policies", "authority_rules", "constraints"))
        out["per_domain"][dom] = {"registered_by_kind": ops, "domain_logic": logic, "domain_adapters": adapters,
                                  "bound_callables_the_generic_engine_needs": bindings_per_domain.get(dom),
                                  "plugin_handlers_the_rival_needs": handlers,
                                  "rival_lifecycle_copies_loc_if_each_action_owns_its_gates": ops.get("actions", 0) * lifecycle}
    out["reading"] = ("Domain logic and adapters are per-domain code in BOTH designs; the generic Engine shares one copy of the lifecycle "
                      f"({lifecycle} LOC) across every action of every domain, a per-domain plugin architecture repeats the gate sequence per "
                      "handler. The count of bound callables is not smaller than the rival's handler count by construction: the difference is "
                      "where the governance code lives, not how much domain code exists.")
    return out
