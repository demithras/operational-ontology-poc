"""PROT-H28 R28-12 (Paladin side, self-run before the frozen audit): the adapter-side modules import no authority / policy /
approval / governance / disclosure module, never read a reply's body or an authority-vocabulary key, and carry no ops-spec
business-rule literal. Known-negative: the scanner flags the mutant module."""
import ast
import json
from pathlib import Path

from paladin.variant import ADAPTER_MODULES

SRC = Path(__file__).resolve().parents[2] / "src"
FORBIDDEN_IMPORT = ("authcompile", "authreplay", "capgraph", "govhooks", "govir", "procedure", "opsrules", "core", "sov", "evid",
                    "extops", "extgate_mut", "histledger", "ledger")
VOCAB = {"approval", "grant", "principal", "role", "policy", "on_behalf_of", "threshold", "decision", "status:approved"}


def rules() -> set:
    out = set()
    for f in (SRC.parent / "spec" / "ops").glob("*.json"):
        for o in json.loads(f.read_text())["operations"]:
            out |= {r["id"] for r in o["business_rules"]}
    return out


def scan(path: Path) -> list:
    tree, hits = ast.parse(path.read_text()), []
    for n in ast.walk(tree):
        names = [a.name for a in n.names] if isinstance(n, ast.Import) else \
            ([n.module or ""] + [f"{n.module}.{a.name}" for a in n.names]) if isinstance(n, ast.ImportFrom) else []
        hits += [f"import {x}" for x in names if x.startswith("paladin.") and x.split(".")[1] in FORBIDDEN_IMPORT]
        if isinstance(n, ast.Attribute) and n.attr == "body":
            hits.append(f"reply body read line {n.lineno}")
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and (n.value in VOCAB or n.value in rules()):
            hits.append(f"literal {n.value!r}")
    return hits


def path_of(mod: str) -> Path:
    return SRC / (mod.replace(".", "/") + ".py")


def test_adapter_modules_are_clean():
    for m in ADAPTER_MODULES:
        assert scan(path_of(m)) == [], m


def test_negative_scanner_flags_the_mutant_module_and_a_synthetic_reply_reader(tmp_path):
    assert any("opsrules" in h for h in scan(path_of("paladin.extgate_mut"))) and any("literal" in h for h in scan(path_of("paladin.extgate_mut")))
    bad = tmp_path / "bad.py"
    bad.write_text("from paladin.core import Core\ndef f(reply):\n    return reply.body.get('approval') == 'grant'\n")
    assert len(scan(bad)) >= 3


def test_engine_adapter_reports_no_observation_in_external_mode():
    from paladin.worldbridge import OutboxAdapter
    assert OutboxAdapter("ERP", {}, lambda x: {}, []).observations() == []
