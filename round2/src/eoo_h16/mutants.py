"""Registered H16 mutants: each injects one defect the audit must catch; the unmutated control must stay clean."""
from __future__ import annotations

import contextlib
import json
from unittest import mock

from eoo_exp.util import ROOT

from . import detectors, loadcheck
from .kernel import live_snapshot

CLASSES = ("domain_special_case", "new_primitive_kind")


def _src(rel: str) -> str:
    return (ROOT / rel).read_text()


def _insert_before(rel: str, anchor: str, code: str) -> dict:
    s = _src(rel)
    assert s.count(anchor) == 1, (rel, anchor, s.count(anchor))
    return {rel: s.replace(anchor, code + anchor)}


def src_mutations() -> dict:
    return {
        "M1_static_domain_id_compare_in_registry": _insert_before(
            "src/eoo_engine/registry.py", "    for kind in DISPATCH_TABLE:\n        handler = DISPATCH_TABLE[kind]\n",
            '    if pkg.get("domain_id") == "manufacturing":\n        pkg = {**pkg, "constraints": []}\n'),
        "M7_static_domain_dict_key_in_validator": _insert_before(
            "src/eoo_ir/validate.py", "def validate(pkg: Any)",
            'SPECIAL = {"project-ontology": lambda p: []}\n\n\n'),
        "M8_static_resource_id_branch_in_pipeline": _insert_before(
            "src/eoo_engine/pipeline.py", "def propose(",
            'def _special(spec):\n    return spec.rid == "attach_evidence"\n\n\n'),
    }


class _FakeHandler:
    kind = "quantities"
    ops: dict = {}

    def compile(self, r, model):
        return None, []


@contextlib.contextmanager
def runtime_domain_branch():
    """Monkeypatch: the loader behaves differently for a package whose domain_id is 'manufacturing'."""
    from eoo_engine import engine, registry
    real = registry.load_model

    def branchy(pkg):
        if pkg.get("domain_id") == "manufacturing":
            pkg = {**pkg, "constraints": []}
        return real(pkg)
    with mock.patch.object(registry, "load_model", branchy), mock.patch.object(engine, "load_model", branchy), \
            mock.patch.object(loadcheck, "load_model", branchy):
        yield


@contextlib.contextmanager
def new_dispatch_kind():
    from eoo_engine import registry
    with mock.patch.dict(registry.DISPATCH_TABLE, {"quantities": _FakeHandler()}):
        yield


@contextlib.contextmanager
def removed_dispatch_kind():
    from eoo_engine import registry
    saved = registry.DISPATCH_TABLE.pop("constraints")
    try:
        yield
    finally:
        registry.DISPATCH_TABLE["constraints"] = saved


@contextlib.contextmanager
def swapped_handler():
    from eoo_engine import registry
    with mock.patch.dict(registry.DISPATCH_TABLE, {"constraints": registry.DISPATCH_TABLE["policies"]}):
        yield


def schema_with_new_array() -> str:
    s = json.loads((ROOT / "ontology/ir.schema.json").read_text())
    s["properties"]["quantities"] = {"type": "array", "items": {"$ref": "#/$defs/objectType"}}
    return json.dumps(s)
