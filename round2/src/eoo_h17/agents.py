"""Agent adversary: an agent tool surface built ONLY from Engine capabilities (call_function / propose_action).

Each attack runs on a fresh Engine; the row records whether the world changed and whether the attack was refused.
``violation`` = the attack achieved something the Function/Action boundary must forbid. Attacks that need only
ordinary API calls are counted; the interpreter-introspection probe is a DISCLOSED LIMIT (docs/engine_semantics.md
section 4: Python is not a sandbox) and is reported but not counted.
"""
from __future__ import annotations

from eoo_engine import CapabilityError, EngineError, SimulatedCrash, WriteGrant
from eoo_engine.capabilities import ReadOnly

from .drivers import new_driver
from .scenarios import for_profile

DANGEROUS = ("Engine", "Store", "Minter", "WriteGrant", "Journal", "State", "AppendOnlyLog", "WmsFake", "GitFake")
WRITE_NAMES = ("store", "engine", "minter", "apply", "grant", "adapters", "journal", "effect_log", "write", "set",
               "update", "create", "delete", "commit", "execute", "approve", "reconcile", "_engine", "_store")
BAD_KINDS = ("write", "apply", "approve", "execute", "reconcile", "raw_write", "delete", "set_state", "journal")


def agent_of(drv) -> str:
    return "agent-1" if drv.DOMAIN == "manufacturing" else "researcher-1"


def run_attack(drv, name, category, fn) -> dict:
    before = drv.marker()
    exc, out = None, {}
    try:
        out = fn(drv) or {}
    except EngineError as e:
        exc = type(e).__name__
    except Exception as e:  # noqa: BLE001 - an unexpected exception type is recorded, never hidden
        exc = f"{type(e).__name__}(unexpected)"
    changed = drv.marker() != before
    return {"attack": name, "category": category, "domain": drv.DOMAIN, "world_changed": changed,
            "refused": exc is not None or bool(out.get("refused")), "exception": exc,
            "unexpected_exception": bool(exc and exc.endswith("(unexpected)")),
            "expected_change": bool(out.get("expected_change")),
            "violation": bool((changed and not out.get("expected_change")) or out.get("violation")), "detail": out.get("detail", "")}


# ---- raw-write attempts through the tool surface ---------------------------------------------------
def a_request_kinds(drv):
    t, bad = drv.engine.tool(agent_of(drv)), []
    for k in BAD_KINDS:
        try:
            t.request(k, {"x": 1})
            bad.append(k)
        except CapabilityError:
            pass
    return {"violation": bool(bad), "detail": f"{len(BAD_KINDS) - len(bad)}/{len(BAD_KINDS)} forbidden request kinds refused; accepted={bad}"}


def a_surface(drv):
    t = drv.engine.tool(agent_of(drv))
    names = sorted(dir(t))
    view = sorted(dir(t.view))
    found = [n for n in WRITE_NAMES if hasattr(t, n) or hasattr(t.view, n)]
    return {"violation": bool(found) or names != ["call_function", "propose_action", "request", "view"],
            "detail": f"tool={names}; view={view}; write-like attributes found={found}"}


def _walk(root, limit=20000):
    seen, stack, hits = set(), [("tool", root)], []
    while stack and len(seen) < limit:
        path, o = stack.pop()
        if id(o) in seen or isinstance(o, (str, int, float, bool, type(None), bytes)) or callable(o) and not isinstance(o, ReadOnly):
            continue
        seen.add(id(o))
        if type(o).__name__ in DANGEROUS:
            hits.append(path)
        if isinstance(o, ReadOnly):
            stack += [(f"{path}.{n}", getattr(o, n)) for n in dir(o)]
        elif isinstance(o, dict):
            stack += [(f"{path}[{k!r}]", v) for k, v in o.items()]
        elif isinstance(o, (list, tuple, set, frozenset)):
            stack += [(f"{path}[]", v) for v in o]
    return len(seen), hits


def a_reachability(drv):
    n, hits = _walk(drv.engine.tool(agent_of(drv)))
    return {"violation": bool(hits), "detail": f"walked {n} non-callable objects from the tool through public attributes; "
                                               f"Engine/Store/Minter/grant/adapter objects reached={hits}"}


def a_setattr(drv):
    t, ok = drv.engine.tool(agent_of(drv)), []
    for tgt in (t, t.view):
        for op in (lambda: setattr(tgt, "get", lambda *a: None), lambda: setattr(tgt, "store", object()),
                   lambda: delattr(tgt, "request" if tgt is t else "get")):
            try:
                op()
                ok.append("mutated")
            except CapabilityError:
                pass
    return {"violation": bool(ok), "detail": f"6 attribute set/delete attempts on tool and view; succeeded={len(ok)}"}


def a_forged_grants(drv):
    e, res = drv.engine, {}
    op = [{"op": "create", "type": "NoSuchType", "key": "k", "props": {}}]
    tries = {"construct": lambda: WriteGrant(),
             "object_new": lambda: e.store.apply(object.__new__(WriteGrant), "x1", op),
             "not_a_grant": lambda: e.store.apply({"token": "t"}, "x1", op),
             "wrong_execution": lambda: e.store.apply(e.minter.mint("x777"), "x1", op)}
    g = e.minter.mint("x1")
    e.minter.revoke(g)
    tries["revoked"] = lambda: e.store.apply(g, "x1", op)
    for k, f in tries.items():
        try:
            f()
            res[k] = "ACCEPTED"
        except CapabilityError:
            res[k] = "refused"
    return {"violation": "ACCEPTED" in res.values(), "detail": str(res)}


def a_unknown_names(drv):
    t, res = drv.engine.tool(agent_of(drv)), {}
    for label, f in (("unknown_action", lambda: t.propose_action("create_object", {})),
                     ("unknown_function", lambda: t.call_function("write_object", {})),
                     ("smuggled_args", lambda: t.call_function(drv_function(drv), {"$write": 1}))):
        try:
            f()
            res[label] = "ACCEPTED"
        except EngineError:
            res[label] = "refused"
    return {"violation": "ACCEPTED" in res.values(), "detail": str(res)}


def drv_function(drv) -> str:
    from .calls import function_specs
    return function_specs(drv.DOMAIN)[0][0]


def a_unauthorized_propose(drv):
    scn = for_profile(drv.DOMAIN, drv.profile, "unauthorized")[0]
    rec = drv.engine.tool(scn.principal).propose_action(scn.action, scn.inputs, idempotency_key="u1")
    return {"refused": rec["state"] == "DENIED", "violation": rec["state"] != "DENIED", "detail": f"{scn.id}: {rec['state']}"}


def a_malicious_function(drv):
    """A Function implementation (domain logic) that tries every ordinary route to a write; bound over a real one."""
    from .calls import function_specs
    attempts = []

    def evil(view, args):
        for name in WRITE_NAMES:
            try:
                getattr(view, name)(1)
                attempts.append(f"{name}: CALLED")
            except (AttributeError, TypeError, CapabilityError):
                pass
        try:
            view.get = None
            attempts.append("setattr: ok")
        except CapabilityError:
            pass
        return 0

    fid = function_specs(drv.DOMAIN)[0][0]
    ref = next(f["implementation_ref"] for f in __import__("domains._pack", fromlist=["load_ir"]).load_ir(drv.DOMAIN)["functions"]
               if f["id"] == fid)
    drv.pack[0].bind("function", ref, evil)
    try:
        drv.engine.call_function(fid, _valid_args(drv, fid))
    except EngineError:
        pass
    return {"violation": bool(attempts),
            "detail": f"malicious {fid} implementation tried {len(WRITE_NAMES) + 1} routes; succeeded={attempts}"}


def _valid_args(drv, fid):
    from .calls import function_specs, _value
    params = dict((f, p) for f, p in function_specs(drv.DOMAIN))[fid]
    return {n: _value(drv, t, 0, False) for n, t, _r in params}


RAW_ATTACKS = [("request_forbidden_kinds", a_request_kinds), ("tool_surface_is_only_function_and_action", a_surface),
               ("reachability_walk", a_reachability), ("setattr_delattr_on_tool_and_view", a_setattr),
               ("forged_or_foreign_write_grants", a_forged_grants), ("unknown_action_function_smuggled_args", a_unknown_names),
               ("unauthorized_propose_via_tool", a_unauthorized_propose), ("malicious_function_implementation", a_malicious_function)]
