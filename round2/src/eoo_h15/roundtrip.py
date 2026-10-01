"""Round-trip one IR through one surface and judge it with the independent oracle."""
from __future__ import annotations

import re
import time

from eoo_ir import equivalent, validate

from .surfaces import Surface
from .util import canon

_IDX = re.compile(r"\[[^\]]*\]")


def norm_path(diff: str) -> str:
    """'actions[x].effects[0].target: a != b' -> 'actions[].effects[].target' (the IR path of a diff)."""
    return _IDX.sub("[]", diff.split(":", 1)[0])


def attempt(s: Surface, ir: dict) -> dict:
    """Outcome of render -> compile -> oracle for one valid IR.

    status: ok | failed | unrepresentable. kind says why (equivalence / typed_error / crash / invalid_output ...).
    """
    t0 = time.perf_counter()
    try:
        art = s.render(ir)
    except s.unrepresentable as e:
        return {"status": "unrepresentable", "kind": "unrepresentable", "code": getattr(e, "code", None),
                "detail": str(e)[:300], "paths": [], "t_render": time.perf_counter() - t0, "t_compile": 0.0}
    except Exception as e:  # noqa: BLE001 - recorded as a failure with its type
        return {"status": "failed", "kind": "render_" + type(e).__name__, "code": getattr(e, "code", None),
                "detail": str(e)[:300], "paths": ["<render>"], "t_render": time.perf_counter() - t0, "t_compile": 0.0}
    t1 = time.perf_counter()
    base = {"t_render": t1 - t0}
    try:
        out = s.compile(art)
    except s.typed_errors as e:
        return {**base, "status": "failed", "kind": "typed_error", "code": getattr(e, "code", type(e).__name__),
                "detail": str(e)[:300], "paths": ["<compile:" + str(getattr(e, "code", type(e).__name__)) + ">"],
                "t_compile": time.perf_counter() - t1, "art": art}
    except Exception as e:  # noqa: BLE001
        return {**base, "status": "failed", "kind": "crash_" + type(e).__name__, "code": None, "detail": str(e)[:300],
                "paths": ["<crash>"], "t_compile": time.perf_counter() - t1, "art": art}
    t2 = time.perf_counter()
    eq = equivalent(ir, out)
    errs = validate(out)
    res = {**base, "t_compile": t2 - t1, "art": art, "exact": canon(out) == canon(ir)}
    if eq.ok and not errs:
        return {**res, "status": "ok", "kind": "equivalent", "paths": []}
    if not eq.ok:
        return {**res, "status": "failed", "kind": "non_equivalent", "detail": "; ".join(eq.diffs[:3])[:400],
                "paths": sorted({norm_path(d) for d in eq.diffs}), "diffs": eq.diffs[:10]}
    return {**res, "status": "failed", "kind": "invalid_output", "detail": str(errs[0])[:300], "paths": ["<ir-invalid>"]}


def public(res: dict) -> dict:
    """Drop the heavy artifact / timing fields before a result goes into evidence."""
    return {k: v for k, v in res.items() if k not in ("art", "t_render", "t_compile")}
