"""Kernel snapshots and diff: before == after (0 new kinds); injected new kinds / schema arrays are visible."""
import json
from unittest import mock

import pytest

from eoo_exp.util import ROOT
from eoo_h16 import mutants as M
from eoo_h16.detectors import changed_is_clean, kernel_diff
from eoo_h16.kernel import live_snapshot, rev_snapshot

oracle = __import__("eoo_exp.util", fromlist=["load_oracle"]).load_oracle("h16", "kernel_oracle")


@pytest.fixture(scope="module")
def snaps():
    return rev_snapshot("r2-engine-core"), rev_snapshot("HEAD")


def test_before_and_after_kernels_are_identical(snaps):
    b, a = snaps
    d = kernel_diff(b, a)
    assert d["new_kernel_primitive_kind_count"] == 0 and changed_is_clean(d) and d["schema_unchanged"]
    assert b["engine_core_files"] == a["engine_core_files"]
    assert d["dispatch_kinds_equal_schema_arrays"] and sorted(a["dispatch"]["handlers"]) == sorted(a["kernel_resource_kinds"])


def test_snapshots_come_from_the_named_commits(snaps):
    b, a = snaps
    assert b["git_commit"].startswith("0aad1ff") and len(a["git_commit"]) == 40 and b["git_commit"] != a["git_commit"]
    assert b["dispatch"]["engine_file"].startswith("<git archive 0aad1ff")


def test_oracle_kernel_kinds_equal_prereg_and_schema_and_dispatch(snaps):
    _, a = snaps
    assert oracle.frozen_kernel_kinds() == oracle.preregistered_kernel_kinds() == sorted(a["dispatch"]["handlers"])
    assert len(oracle.frozen_kernel_kinds()) == 9


def test_live_snapshot_equals_head(snaps):
    _, a = snaps
    live = live_snapshot()
    assert live["dispatch"]["handlers"] == a["dispatch"]["handlers"] and live["ir_schema"] == a["ir_schema"]


def test_new_dispatch_kind_is_a_new_primitive(snaps):
    b, _ = snaps
    with M.new_dispatch_kind():
        d = kernel_diff(b, live_snapshot())
    assert d["new_kernel_primitive_kinds"] == ["quantities"] and d["dispatch_added"] == ["quantities"]
    assert kernel_diff(b, live_snapshot())["new_kernel_primitive_kind_count"] == 0  # restored


def test_new_schema_array_is_a_new_primitive(snaps):
    b, _ = snaps
    d = kernel_diff(b, live_snapshot(schema_text=M.schema_with_new_array()))
    assert d["new_kernel_primitive_kinds"] == ["quantities"] and d["schema_resource_arrays_added"] == ["quantities"]
    assert not d["dispatch_kinds_equal_schema_arrays"]


def test_new_prereg_kind_is_a_new_primitive(snaps):
    b, _ = snaps
    pre = json.loads((ROOT / "protocol/ENGINE_PREREG.json").read_text())
    pre["kernel_snapshot"]["kernel_resource_kinds"].append("quantities")
    d = kernel_diff(b, live_snapshot(prereg_text=json.dumps(pre)))
    assert d["new_kernel_primitive_kinds"] == ["quantities"]


def test_a_swapped_handler_is_visible(snaps):
    b, _ = snaps
    with M.swapped_handler():
        d = kernel_diff(b, live_snapshot())
    assert d["dispatch_handlers_changed"] == ["constraints"] and not changed_is_clean(d)


def test_oracle_does_not_import_engine_toolchain_or_domain_logic():
    import ast
    src = (ROOT / "oracles/h16/kernel_oracle.py").read_text()
    names = []
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            names += [a.name for a in n.names]
        if isinstance(n, ast.ImportFrom):
            names.append(n.module or "")
    assert not [x for x in names if x.startswith(("eoo_engine", "eoo_toolchain", "domains"))], names
