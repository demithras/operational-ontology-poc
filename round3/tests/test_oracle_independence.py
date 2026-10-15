"""The oracle may not import candidate code; the effect meter may not read CallResult."""
import ast
import tempfile
from pathlib import Path

from r3_harness.h23.evaluator import oracle_independent
from r3_oracle.effect_meter import EffectMeter
from r3_shared.world import WorldStore

ORACLE = Path(__file__).resolve().parents[1] / "src" / "r3_oracle"


def test_oracle_imports_only_shared_and_itself():
    ok, bad = oracle_independent()
    assert ok, bad
    roots = set()
    for f in ORACLE.glob("*.py"):
        for n in ast.walk(ast.parse(f.read_text())):
            if isinstance(n, ast.ImportFrom) and n.level == 0:
                roots.add(n.module.split(".")[0])
            elif isinstance(n, ast.Import):
                roots |= {a.name.split(".")[0] for a in n.names}
    assert {r for r in roots if r.startswith(("r3_", "paladin", "conventional", "eoo"))} <= {"r3_shared"}


def test_meter_never_touches_status_or_body_and_does_not_import_variant_module():
    tree = ast.parse((ORACLE / "effect_meter.py").read_text())
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not attrs & {"status", "body"}
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert "r3_shared.variant" not in mods


def test_known_negative_the_independence_check_fires_on_a_bad_oracle(tmp_path, monkeypatch):
    import r3_harness.h23.evaluator as ev
    fake_root = tmp_path / "src" / "r3_oracle"
    fake_root.mkdir(parents=True)
    (fake_root / "bad.py").write_text("from paladin.engine import x\nimport conventional\n")
    (fake_root / "effect_meter.py").write_text("def f(r):\n    return r.status\n")
    monkeypatch.setattr(ev, "ROUND3", tmp_path)
    ok, bad = ev.oracle_independent()
    assert not ok and len(bad) == 3


def test_meter_measures_world_diff_not_return_values():
    store = WorldStore(Path(tempfile.mkdtemp()) / "w.db")
    h = store.handle("w")
    m = EffectMeter(store.reader())
    ret, eff, before = m.measure(lambda: (h.create("T", "k", {"a": 1}), "I did nothing")[1])
    assert ret == "I did nothing" and [(e["kind"], e["ref"]) for e in eff] == [("create", "T:k")]
    _, eff2, _ = m.measure(lambda: "claims success")
    assert eff2 == []
    _, eff3, _ = m.measure(lambda: h.external_write("WMS", "transfer", {"q": 1}))
    assert eff3[0]["kind"] == "external" and eff3[0]["writer"] == "w"
