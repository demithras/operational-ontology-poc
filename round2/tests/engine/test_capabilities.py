"""Functions/tools get read-only capabilities; writes need a live WriteGrant minted by the pipeline."""
from types import FunctionType, MappingProxyType

import pytest

from eoo_engine import CapabilityError, InvalidRequest, WriteGrant
from eoo_engine.capabilities import Minter, ReadOnly
from eoo_engine.engine import Engine
from eoo_engine.state import State
from eoo_engine.store import Store
from synth import build, effects_of

WRITE_WORDS = ("write", "apply", "put", "set", "create", "update", "delete", "insert", "remove", "seed", "commit",
               "mint", "link", "unlink", "record", "append", "store", "journal")
FORBIDDEN_TYPES = (Store, State, Minter, Engine, WriteGrant)


def _is_write_name(n: str) -> bool:
    return any(tok in WRITE_WORDS for tok in n.lower().strip("_").split("_"))


def _attrs(obj):
    names = set(n for n in dir(obj) if not n.startswith("__"))
    for cls in type(obj).__mro__:
        names |= {n for n in getattr(cls, "__slots__", ()) if not n.startswith("__")}
    return names


def reachable(root, limit=20000):
    """Everything reachable through non-dunder attributes and container items (interpreter
    introspection such as __closure__/__globals__/gc is outside the guarantee, see capabilities.py)."""
    seen, todo, out = set(), [root], []
    while todo and len(seen) < limit:
        o = todo.pop()
        if id(o) in seen or isinstance(o, (str, bytes, int, float, bool, type(None), type)):
            continue
        seen.add(id(o))
        out.append(o)
        if isinstance(o, (dict, MappingProxyType)):
            todo += list(o.keys()) + list(o.values())
            continue
        if isinstance(o, (list, tuple, set, frozenset)):
            todo += list(o)
            continue
        if isinstance(o, ReadOnly):
            todo.append(object.__getattribute__(o, "_fields"))
            continue
        for n in _attrs(o):
            try:
                todo.append(getattr(o, n))
            except Exception:
                pass
    return out


def test_read_view_has_no_write_path():
    eng, _, _ = build()
    view = eng.read_view()
    assert not [n for n in dir(view) if _is_write_name(n)]
    objs = reachable(view)
    assert not [o for o in objs if isinstance(o, FORBIDDEN_TYPES)]
    with pytest.raises(CapabilityError):
        view.get = lambda *a: None
    rec = view.get("Box", "b1")
    with pytest.raises(TypeError):
        rec["props"]["level"] = 99
    assert eng.get("Box", "b1")["props"]["level"] == 10


def test_function_that_tries_to_write_fails_and_writes_nothing():
    eng, _, _ = build()
    attempts, refused = [], []

    def sneaky(view, args):
        for o in reachable(view):  # call every write-named method reachable from the view
            for n in _attrs(o):
                if _is_write_name(n):
                    try:
                        getattr(o, n)({})
                        attempts.append(f"SUCCEEDED {type(o).__name__}.{n}")
                    except CapabilityError:
                        refused.append(n)
        try:
            view.objects = {}
        except CapabilityError:
            attempts.append("setattr-refused")
        try:
            view.get("Box", args["box"])["props"]["level"] = 0
        except TypeError:
            attempts.append("mutation-refused")
        return 1

    eng.bindings.bind("function", "impl:box_level", sneaky)
    h = eng.state().state_hash()
    assert eng.call_function("box_level", {"box": "b1"}) == 1
    assert attempts == ["setattr-refused", "mutation-refused"] and eng.state().state_hash() == h
    assert len(eng.effect_log) == 0 and refused  # write-named methods were reachable only as refusing stubs


def test_function_typed_inputs_and_output():
    eng, _, _ = build()
    assert eng.call_function("box_level", {"box": "b1"}) == 10
    for bad in ({"box": "zzz"}, {}, {"box": 1}, {"box": "b1", "x": 1}):
        with pytest.raises(InvalidRequest):
            eng.call_function("box_level", bad)
    eng.bindings.bind("function", "impl:box_level", lambda view, args: "ten")
    with pytest.raises(Exception, match="output"):
        eng.call_function("box_level", {"box": "b1"})


def test_store_rejects_writes_without_valid_live_grant():
    eng, _, _ = build()
    op = [{"op": "update", "type": "Box", "key": "b1", "props": {"level": 0}}]
    with pytest.raises(CapabilityError):
        WriteGrant()
    forged = object.__new__(WriteGrant)
    object.__setattr__(forged, "execution", "x1")
    object.__setattr__(forged, "token", "0" * 32)
    other = Minter().mint("x1")  # minted by a foreign minter
    live = eng.minter.mint("x1")
    eng.minter.revoke(live)
    for g in (None, forged, other, live, "x1"):
        with pytest.raises(CapabilityError):
            eng.store.apply(g, "x1", op)
    wrong_exec = eng.minter.mint("x2")
    with pytest.raises(CapabilityError):
        eng.store.apply(wrong_exec, "x1", op)
    assert eng.get("Box", "b1")["props"]["level"] == 10


def test_adapter_call_needs_grant():
    eng, _, carrier = build()
    rec = eng.propose("fill_box", {"box": "b1", "amount": 60}, "filler", idempotency_key="k")
    spec = eng.model.get("actions", "ship_box")
    with pytest.raises(CapabilityError):
        eng.call_adapter(None, rec, spec, spec.effects[0], {"box": "b1"})
    assert carrier.calls == []


def test_tool_can_only_call_functions_or_propose():
    eng, _, _ = build()
    tool = eng.tool("filler")
    assert tool.call_function("box_level", {"box": "b1"}) == 10
    rec = tool.propose_action("fill_box", {"box": "b1", "amount": 2}, idempotency_key="t")
    assert rec["state"] == "RECONCILED_SUCCESS" and len(effects_of(eng, rec["exec"])) == 1
    for kind in ("write", "update", "seed", "apply"):
        with pytest.raises(CapabilityError):
            tool.request(kind, "Box", {"level": 0})
    assert not [o for o in reachable(tool) if isinstance(o, FORBIDDEN_TYPES)]
    assert not [n for n in dir(tool) if n in ("store", "engine", "minter")]
    assert all(isinstance(getattr(tool, n), (FunctionType, ReadOnly)) for n in dir(tool))


def test_tool_with_unknown_principal_is_denied():
    eng, _, _ = build()
    rec = eng.tool("ghost").propose_action("fill_box", {"box": "b1", "amount": 2}, idempotency_key="t")
    assert rec["state"] == "DENIED" and rec["gates"][-1]["gate"] == "identity"
