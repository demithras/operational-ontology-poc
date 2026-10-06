"""Gate oracle independence + evaluator-vs-oracle cross-check on generated scenario shapes (LIMITED role: not trend evidence)."""
import ast
import shutil
import tempfile
from pathlib import Path

import pytest
from conftest import CLASSES, ROOT, make_case
from hypothesis import example, given, strategies as st

from eoo_h22.evaluate import evaluate

FORBIDDEN = {"eoo_engine", "eoo_engine_git", "eoo_toolchain", "domains", "eoo_h22", "eoo_ir", "hdd", "eoo_exp", "eoo_h21", "eoo_h20"}


def imports_of(src):
    out = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            out |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            out.add((n.module or "").split(".")[0])
    return out


def test_oracle_imports_nothing_from_engine_toolchain_or_domains():
    files = sorted((ROOT / "oracles/h22").glob("*.py"))
    assert [f.name for f in files] == ["__init__.py", "gate_oracle.py"]
    for f in files:
        assert imports_of(f.read_text()) & FORBIDDEN == set(), f.name


def test_import_checker_known_negative():
    assert imports_of("from eoo_engine import x\nimport hdd.verdict") == {"eoo_engine", "hdd"}


RATIOS = st.sampled_from([0.5, 0.75, 0.8, 0.9, 0.95, 1.2])


@st.composite
def scenario(draw):
    lo, slope, hi = sorted([draw(st.sampled_from([0.3, 0.5, 0.7, 0.75, 0.8, 0.9, 1.0, 1.1])) for _ in range(3)])
    return dict(domains=draw(st.integers(0, 5)), tasks=draw(st.sampled_from([0, 10, 29, 30, 31, 40])), noninf=draw(st.booleans()), tier=draw(st.booleans()),
                fair=draw(st.booleans()), regress=draw(st.sampled_from([0, 0, 1])), slope=slope, ci=(lo, hi), class_ratio={c: draw(RATIOS) for c in CLASSES})


def oracle_case(s):
    ratios = {c: [] for c in CLASSES}
    for i in range(s["tasks"] if s["domains"] else 0):
        ratios[CLASSES[i % 5]].append(s["class_ratio"][CLASSES[i % 5]])
    return {"domains": s["domains"], "tasks": s["tasks"] if s["domains"] else 0, "class_ratios": ratios, "noninferior": {c: s["noninf"] for c in CLASSES},
            "slope": s["slope"], "ci": list(s["ci"]), "tier": s["tier"], "fair_persist": s["fair"], "regressions": s["regress"]}


_POS = dict(domains=3, tasks=30, noninf=True, tier=True, fair=True, regress=0, slope=0.5, ci=(0.3, 0.7), class_ratio={c: 0.5 for c in CLASSES})


@given(scenario())
@example(_POS)
@example({**_POS, "domains": 2})
@example({**_POS, "fair": False})
@example({**_POS, "slope": 1.0, "ci": (1.0, 1.0)})
def test_evaluator_agrees_with_the_independent_oracle(s):
    from importlib.util import module_from_spec, spec_from_file_location
    spec = spec_from_file_location("gate_oracle", ROOT / "oracles/h22/gate_oracle.py")
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)
    base = Path(tempfile.mkdtemp(prefix="h22prop"))
    try:
        d = base / "ev"
        shutil.copytree(REAL[0], d)
        (d / "verdict.json").unlink(missing_ok=True)
        make_case(d, domains=max(s["domains"], 1), tasks=s["tasks"], slope=s["slope"], ci=s["ci"], noninf=s["noninf"], tier=s["tier"], fair=s["fair"],
                  regress=s["regress"], class_ratio=s["class_ratio"])
        if s["domains"] == 0:  # no real domain at all
            from conftest import rewrite
            rewrite(d, "domain-manifest.json", lambda p: p.update(real_domains=[], real_domain_count=0))
        got = evaluate(d)["verdict"]
    finally:
        shutil.rmtree(base, ignore_errors=True)
    SEEN[got] = SEEN.get(got, 0) + 1
    assert got == mod.verdict(oracle_case(s)), s


REAL: list = []
SEEN: dict = {}


@pytest.fixture(autouse=True, scope="module")
def _real(real_run):
    REAL[:] = [real_run]


def test_zz_property_run_reached_every_verdict_class():
    assert {"SUPPORTED", "REJECTED", "INCONCLUSIVE"} <= set(SEEN), SEEN
