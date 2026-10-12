"""P1g-9/P1g-10 and edges: G5 harness entries (NotImplementedError for variants that lack the surface), frozen H29 mutant names, import
edges for the new services, launcher refusals for all three services (one test each)."""
import ast
import inspect
from pathlib import Path

import pytest

from r3_shared import mutants
from r3_shared.anchor import AnchorError, require_anchor
from r3_shared.authsvc import AuthorityError, require_authority
from r3_shared.extworld import ExternalError, require_external
from r3_shared.registry import VARIANTS, load_variant
from r3_shared.variant import G5_METHODS, g5_call, g5_deploy
from tests.fakes.fake_variant import FakeDeployment, FakeVariant
from tests.fakes.fake_g5 import FakeG5Variant

SRC = Path(__file__).resolve().parents[1] / "src"
H29 = ["fail_open_on_authority_outage", "global_halt_on_fault", "stale_cache_after_restart", "nondeterministic_recovery",
       "dependency_failure_as_denial", "outbox_dropped_on_restart", "anchor_skipped_when_unavailable"]


def test_h29_mutant_names_exactly_as_frozen():
    assert mutants.KNOWN["H29"] == H29
    assert mutants.validate(H29) == frozenset(H29)
    assert FakeVariant(["global_halt_on_fault"]).mutants == frozenset({"global_halt_on_fault"})
    assert len(mutants.ALL) == sum(len(v) for v in mutants.KNOWN.values())          # no name shared between gates
    with pytest.raises(ValueError):
        mutants.validate(["fail_open_on_authority_outages"])


def test_g5_entries_raise_not_implemented_for_missing_surface():
    assert G5_METHODS == ("recovery_view", "dependency_status")
    for m in G5_METHODS:
        with pytest.raises(NotImplementedError, match="not implemented yet - G5"):
            g5_call(object(), m)
    with pytest.raises(ValueError):
        g5_call(object(), "reconcile")
    with pytest.raises(NotImplementedError, match="not implemented yet - G5"):
        g5_deploy(FakeVariant(), "manufacturing", None, None, {}, {}, None, authority_source=None)    # the old fake lacks the params


def test_fake_g5_has_the_surface_and_registry_variants_report_the_gap_honestly():
    assert {"recovery_view", "dependency_status"} <= {n for n, _ in inspect.getmembers(FakeG5Variant.deployment_class)}
    assert "authority_source" in inspect.signature(FakeG5Variant().deploy).parameters
    for name in sorted(VARIANTS):                      # registry conformance: a variant without the G5 seam says so, never TypeError
        try:
            v = load_variant(name)
        except NotImplementedError:
            continue
        params = inspect.signature(v.deploy).parameters
        if {"authority_source", "resume"} <= set(params):
            continue                                   # a built G5 seam: its own conformance (C29-1..7) covers it
        with pytest.raises(NotImplementedError, match="not implemented yet - G5"):
            g5_deploy(v, "manufacturing", None, None, {}, {}, None, authority_source=None)


def _imports(src):
    out = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            out += [(a.name, node.lineno) for a in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level:
            out += [(node.module or "", node.lineno)] + [(f"{node.module}.{a.name}", node.lineno) for a in node.names]
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append((node.value, node.lineno))
        elif isinstance(node, ast.Name):
            out.append((node.id, node.lineno))
    return out


HARNESS_ONLY = ("r3_shared.authsvc_server", "r3_shared.host", "r3_shared.extworld_server", "r3_shared.extworld_core", "r3_shared.anchor_server")
CONTROL_NAMES = ("AuthorityControl", "AnchorControl", "ExternalWorldCore", "DeploymentProxy")


@pytest.mark.parametrize("pkg", ["paladin", "conventional", "r3_oracle"])
def test_variants_and_oracle_never_touch_services_hosts_or_control_planes(pkg):
    hits = []
    for f in sorted((SRC / pkg).rglob("*.py")) if (SRC / pkg).exists() else []:
        for name, line in _imports(f.read_text()):
            if any(name == h or name.startswith(h + ".") for h in HARNESS_ONLY) or name in CONTROL_NAMES:
                hits.append(f"{f.relative_to(SRC)}:{line}: {name}")
    assert hits == []


def test_scanner_known_negatives():
    for bad in ("import r3_shared.host", "from r3_shared.authsvc_server import main", "x = AuthorityControl", "import importlib\nimportlib.import_module('r3_shared.host')"):
        assert [n for n, _ in _imports(bad) if any(n == h or n.startswith(h + ".") for h in HARNESS_ONLY) or n in CONTROL_NAMES]
    assert not [n for n, _ in _imports("from r3_shared.authsvc import AuthorityClient") if n in CONTROL_NAMES or n.startswith("r3_shared.authsvc_server")]


# ---- G3-E31b lifecycle: a non-dev id refuses to run when a service socket is not reachable (all three) ----------------------
def test_refusal_anchor_not_reachable():
    with pytest.raises(AnchorError, match="requires R3_ANCHOR_SOCK"):
        require_anchor("exp-h29-001", env={})
    with pytest.raises(AnchorError, match="is not running"):
        require_anchor("exp-h29-001", env={"R3_ANCHOR_SOCK": "/tmp/r3-gone", "R3_ANCHOR_DIR": "/tmp"})


def test_refusal_external_world_not_reachable():
    with pytest.raises(ExternalError, match="requires R3_EXT_SOCK"):
        require_external("exp-h29-001", env={})
    with pytest.raises(ExternalError, match="is not running"):
        require_external("exp-h29-001", env={"R3_EXT_SOCK": "/tmp/r3-gone", "R3_EXT_CTL": "/tmp/r3-gone.ctl", "R3_EXT_DIR": "/tmp"})


def test_refusal_authority_service_not_reachable():
    with pytest.raises(AuthorityError, match="requires R3_AUTH_SOCK"):
        require_authority("exp-h29-001", env={})
    with pytest.raises(AuthorityError, match="is not running"):
        require_authority("exp-h29-001", env={"R3_AUTH_SOCK": "/tmp/r3-gone", "R3_AUTH_CTL": "/tmp/r3-gone.ctl", "R3_AUTH_DIR": "/tmp"})
