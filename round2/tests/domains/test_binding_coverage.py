"""Binding coverage: 0 unbound IR references per domain, no dead bindings, no constant stubs."""
from __future__ import annotations

import dis

import pytest

from domains._pack import boot, load_ir
from domains.manufacturing.pack import build_pack as mfg_pack
from domains.project.pack import build_pack as prj_pack
from eoo_engine import Engine, LoadError, LogicBindings, required_bindings

PACKS = {"manufacturing": mfg_pack, "project": prj_pack}
_CONST_OPS = {"RESUME", "LOAD_CONST", "RETURN_VALUE", "RETURN_CONST", "NOP", "CACHE", "PUSH_NULL", "LOAD_SMALL_INT"}


def _is_constant_stub(fn) -> bool:
    return {i.opname for i in dis.get_instructions(fn)} <= _CONST_OPS


def _unbound(domain: str) -> list:
    bindings, adapters, _seed = PACKS[domain]()
    from eoo_engine import AdapterRegistry
    reg = AdapterRegistry(adapters)
    return [u for u in required_bindings(load_ir(domain))
            if (u.kind == "adapter" and reg.lookup(*u.key.split(":", 1)) is None)
            or (u.kind != "adapter" and not bindings.has(u.kind, u.key))]


@pytest.mark.parametrize("domain", sorted(PACKS))
def test_zero_unbound_references(domain):
    req = required_bindings(load_ir(domain))
    assert len(req) >= 40  # the IR really asks for many bindings (sanity: not an empty requirement list)
    assert [str(u) for u in _unbound(domain)] == []
    boot(domain, PACKS[domain]())  # Engine.__init__ raises LoadError on any Unbound item


@pytest.mark.parametrize("domain", sorted(PACKS))
def test_every_binding_is_used_by_the_ir_and_none_is_a_constant(domain):
    bindings, _, _ = PACKS[domain]()
    needed = {(u.kind, u.key) for u in required_bindings(load_ir(domain))}
    ir = load_ir(domain)
    effects = {f"{a['id']}#{i}" for a in ir["actions"] for i in range(len(a["effects"]))}
    # a payload binding is optional (the Engine derives simple payloads), so it only has to name a real effect
    dead = [k for k in bindings.keys() if k not in needed and not (k[0] == "payload" and k[1] in effects)]
    assert dead == [], f"bindings the IR never asks for: {dead}"
    stubs = [k for k in bindings.keys() if _is_constant_stub(bindings.get(*k))]
    assert stubs == [], f"constant stubs: {stubs}"


def test_checker_known_negatives():
    """The coverage checker itself: an empty pack leaves everything unbound; a constant stub is detected."""
    for domain in PACKS:
        with pytest.raises(LoadError) as ei:
            Engine(load_ir(domain), LogicBindings(), {})
        assert len(ei.value.problems) == len(required_bindings(load_ir(domain)))
    assert _is_constant_stub(lambda c: True) and _is_constant_stub(lambda v, a: 0)
    assert not _is_constant_stub(lambda c: bool(c.inputs))
    bindings, adapters, _ = mfg_pack()
    b2 = LogicBindings()
    for k in bindings.keys():
        if k != ("policy", next(k2[1] for k2 in bindings.keys() if k2[0] == "policy")):
            b2.bind(k[0], k[1], bindings.get(*k))
    with pytest.raises(LoadError):
        Engine(load_ir("manufacturing"), b2, adapters)
