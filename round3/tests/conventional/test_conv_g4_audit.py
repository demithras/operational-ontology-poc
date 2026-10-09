"""R28-12 self-audit of ADAPTER_MODULES (our own static scan; the harness scan is the frozen one): the import closure of adapter-side
code never reaches authority / policy / approval / governance / disclosure modules, and the clean build has no reply-key reads."""
import ast
import importlib
import importlib.util
from pathlib import Path

from conventional.variant import ADAPTER_MODULES, EXTERNAL_HISTORY_PREFIXES

FORBIDDEN_MODULES = ("pdp", "policy", "authdoc", "authority_ops", "govsvc", "govproc", "govstore", "govbook", "lowview", "lowreads",
                     "lowprov", "lowevents", "provenance", "service", "interp", "r3_shared.authgraph", "r3_shared.authspec",
                     "r3_shared.governance", "r3_shared.disclosure", "r3_shared.constitutional")
VOCAB = ("grant", "principal", "role", "approval", "policy", "on_behalf_of", "threshold", "decision")


def _closure(mod: str, seen=None) -> set:
    seen = seen if seen is not None else set()
    if mod in seen or not mod.startswith(("conventional", "r3_shared")):
        return seen
    seen.add(mod)
    tree = ast.parse(Path(importlib.import_module(mod).__file__).read_text())
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            if n.level:
                pkg = mod.rsplit(".", n.level)[0] if "." in mod else mod
                root = pkg + ("." + n.module if n.module else "")
                for a in n.names:
                    _closure(root + "." + a.name, seen) if _is_mod(root + "." + a.name) else _closure(root, seen)
            elif n.module:
                _closure(n.module, seen)
        elif isinstance(n, ast.Import):
            for a in n.names:
                _closure(a.name, seen)
    return seen


def _is_mod(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def test_declarations_exist():
    assert ADAPTER_MODULES and all(importlib.import_module(m) for m in ADAPTER_MODULES)
    assert isinstance(EXTERNAL_HISTORY_PREFIXES, tuple)


def test_adapter_closure_never_reaches_the_decision_plane():
    closure = set()
    for m in ADAPTER_MODULES:
        _closure(m, closure)
    bad = [c for c in closure if any(c == f or c.endswith("." + f) for f in FORBIDDEN_MODULES)]
    assert not bad, bad


def test_adapter_modules_read_no_authority_vocabulary_outside_mutant_guards():
    for m in ADAPTER_MODULES:
        tree = ast.parse(Path(importlib.import_module(m).__file__).read_text())
        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef,))]:
            for n in ast.walk(fn):
                if isinstance(n, (ast.Compare, ast.Subscript, ast.Attribute)):
                    txt = ast.unparse(n).lower()
                    txt = txt.replace("policy_gate_in_adapter", "")  # the mutant switch NAME is not a rule (G4-E25(b))
                    assert not any(v in txt for v in VOCAB), (m, fn.name, txt)


def test_known_negative_the_closure_scan_flags_the_service_module():
    """Prove the checker on a known-negative: the service module (decision plane) pulls in the forbidden modules."""
    c = _closure("conventional.service")
    assert any(x.endswith("pdp") for x in c) and any(x.endswith("govsvc") for x in c)


def test_closure_of_adapter_modules_is_small_and_listed():
    c = set()
    for m in ADAPTER_MODULES:
        _closure(m, c)
    assert {"conventional.extout", "conventional.extrecon", "r3_shared.extcap", "r3_shared.extobs"} <= c


def test_mutant_only_module_is_outside_the_clean_build_and_inside_the_mutant_build():
    from conventional.variant import ConventionalVariant
    assert "conventional.extgate_mut" not in ConventionalVariant().adapter_modules
    assert "conventional.extgate_mut" in ConventionalVariant(["policy_gate_in_adapter"]).adapter_modules
    closure = set()
    for m in ConventionalVariant().adapter_modules:
        _closure(m, closure)
    assert "conventional.extgate_mut" not in closure


def test_runner_static_scan_clean_build_zero_unresolved_mutant_build_hits_moved_rule():
    from r3_harness.h28 import audit
    from conventional.variant import ConventionalVariant
    lits = audit.all_literals()
    clean = audit.static_scan("conventional", list(ConventionalVariant().adapter_modules), lits)
    mut = audit.static_scan("conventional", list(ConventionalVariant(["policy_gate_in_adapter"]).adapter_modules), lits)
    assert clean["unresolved_count"] == 0, clean["hits"]
    assert mut["unresolved_count"] >= 2 and any("extgate_mut" in h["file"] for h in mut["hits"])
