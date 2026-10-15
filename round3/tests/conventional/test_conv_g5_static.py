"""C29-7: the dependency graph is DATA - no per-domain dependency literal in the G5 modules of the conventional variant, and the variant
never reads the graph file itself (it only receives AuthorityBinding.graph)."""
import ast
import json
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "conventional"
G5 = ("g5deps.py", "g5svc.py", "g5journal.py")
GRAPH = json.loads((Path(__file__).resolve().parents[2] / "spec" / "gate5" / "dependency-graph.json").read_text())


def literals(path):
    return {n.value for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def test_no_domain_or_system_or_operation_names_in_g5_modules():
    forbidden = {op for k, d in GRAPH["operations"].items() if k != "*" for op in d} | {s for d in GRAPH["systems"].values() for s in d} \
        | set(GRAPH["systems"]) - {"*"}
    forbidden |= {n for ns in (v for d in GRAPH["systems"].values() for v in d.values()) for n in ns if n.startswith("EXT:")}
    for f in G5:
        hit = literals(SRC / f) & forbidden
        assert not hit, (f, hit)


def test_known_negative_the_scan_does_see_a_planted_literal(tmp_path):
    p = tmp_path / "plant.py"
    p.write_text('X = "EXT:ERP"\nY = "transfer_inventory"\n')
    assert literals(p) & {"EXT:ERP", "transfer_inventory"} == {"EXT:ERP", "transfer_inventory"}


def test_variant_never_opens_the_graph_file():
    for f in G5:
        assert "dependency-graph" not in (SRC / f).read_text()
