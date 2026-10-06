"""Static audit: the Engine core is domain-blind (ENGINE_PREREG H20 forbidden_core_tokens)."""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "src" / "eoo_engine"
RESOURCE_ARRAYS = ("object_types", "link_types", "interfaces", "functions", "actions", "policies", "authority_rules",
                   "observation_types", "constraints")


def _schema_vocabulary() -> set:
    """Words the frozen IR schema itself defines (keys, enum/const values): the Engine must read IR
    documents by these keys, so a domain property that happens to share one (e.g. ``id``) is not a leak."""
    out = set()

    def walk(n):
        if isinstance(n, dict):
            for k, v in n.items():
                if k in ("properties", "$defs") and isinstance(v, dict):
                    out.update(v)
                if k == "enum":
                    out.update(x for x in v if isinstance(x, str))
                if k == "const" and isinstance(v, str):
                    out.add(v)
                if k == "required" and isinstance(v, list):
                    out.update(v)
                walk(v)
        elif isinstance(n, list):
            for x in n:
                walk(x)
    walk(json.loads((ROOT / "ontology" / "ir.schema.json").read_text()))
    return out


def _prereg_engine_vocabulary() -> set:
    """Engine words fixed by protocol/ENGINE_PREREG.json before any Engine code (H17 gate tokens)."""
    pre = json.loads((ROOT / "protocol" / "ENGINE_PREREG.json").read_text())
    return set(pre["H17"]["gate_tokens"])


def domain_tokens() -> tuple[set, set]:
    """(resource ids + package/domain ids, property/parameter names) of every domains/*/ir.json."""
    ids, names = set(), set()
    files = sorted((ROOT / "domains").glob("*/ir.json"))
    assert len(files) >= 2, files
    for f in files:
        pkg = json.loads(f.read_text())
        ids |= {pkg["package_id"], pkg.get("domain_id", "")} - {""}
        for kind in RESOURCE_ARRAYS:
            for r in pkg[kind]:
                ids.add(r["id"])
                for key in ("properties", "required_properties", "inputs"):
                    names |= {p["name"] for p in r.get(key, [])}
    return ids, names


def core_literals() -> dict:
    out = {}
    for f in sorted(CORE.glob("*.py")):
        for node in ast.walk(ast.parse(f.read_text(), str(f))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                out.setdefault(node.value, []).append(f"{f.name}:{node.lineno}")
    return out


def test_no_domain_identifier_appears_as_a_core_string_literal():
    ids, names = domain_tokens()
    vocab = _schema_vocabulary() | _prereg_engine_vocabulary()
    forbidden = ids | (names - vocab)  # resource/package ids are never excused
    lits = core_literals()
    hits = {t: lits[t] for t in sorted(forbidden) if t in lits}
    assert not hits, hits
    assert len(forbidden) > 300 and len(lits) > 200  # the audit is not vacuous


def test_audit_catches_a_planted_identifier():
    ids, _ = domain_tokens()
    planted = sorted(ids)[0]
    tree = ast.parse(f"x = {planted!r}")
    assert any(isinstance(n, ast.Constant) and n.value in ids for n in ast.walk(tree))


def test_core_never_imports_or_reads_domains():
    for f in sorted(CORE.glob("*.py")):
        src = f.read_text()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Import):
                assert not any("domains" in a.name for a in node.names), f
            if isinstance(node, ast.ImportFrom):
                assert "domains" not in (node.module or ""), f
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert "domains/" not in node.value and "domains\\\\" not in node.value, (f, node.value)
