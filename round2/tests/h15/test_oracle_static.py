"""Contamination rule (AGENTS.md section 10): the oracle must not import or mention the candidate language."""
import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "eoo_ir"
BANNED = "openpona"


def test_package_exists_and_is_nonempty():
    assert len(list(SRC.glob("*.py"))) >= 8


def test_no_module_imports_or_mentions_the_candidate_language():
    for path in sorted(SRC.rglob("*.py")):
        text = path.read_text()
        assert BANNED not in text.lower(), f"{path.name} mentions the candidate language"
        for node in ast.walk(ast.parse(text)):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            assert not any(BANNED in n.lower() for n in names), (path.name, names)


def test_static_check_has_teeth():
    """Known-positive: the same scan must flag a module that does mention it."""
    bad = "import openpona_compiler\n"
    assert BANNED in bad.lower()
    tree = ast.parse(bad)
    assert any(BANNED in a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names)


def test_the_whole_phase_is_free_of_the_candidate_language():
    """Gate 0 data and code: DSL baseline, domain IR, ambiguity classes/cases, notes, builder scripts."""
    root = SRC.parents[1]
    files = [p for d in ("src/eoo_dsl", "domains", "scripts/domain_build") for p in (root / d).rglob("*") if p.is_file() and p.suffix in
             (".py", ".json", ".yaml", ".md")]
    files += [root / "protocol/h15_ambiguity_classes.json", root / "ontology/h15_oracle_notes.md", root / "tests/h15/dsl_ambiguity_cases.jsonl",
              root / "scripts/build_domain_ir.py", root / "scripts/build_dsl_ambiguity_cases.py", root / "scripts/build_oracle_notes.py"]
    assert len(files) > 20
    hits = [str(f.relative_to(root)) for f in files if BANNED in f.read_text().lower()]
    assert not hits, hits
