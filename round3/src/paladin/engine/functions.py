"""Calling IR Functions: typed inputs in, read-only view, typed output out. No write path exists."""
from __future__ import annotations

from typing import Any

from .canon import freeze, to_plain
from .errors import EngineError, InvalidRequest
from .typecheck import check


class FunctionOutputError(EngineError):
    """The bound implementation returned a value outside the declared output type."""


def check_params(params: tuple, args: Any, state, where: str) -> list[str]:
    """Problems of ``args`` against IR parameters (unknown, missing required, wrong type)."""
    if not hasattr(args, "items"):
        return [f"{where}: arguments must be a mapping"]
    errs = []
    names = {p.pname for p in params}
    for k in args:
        if k not in names:
            errs.append(f"{where}: unknown parameter {k!r}")
    for p in params:
        if p.pname not in args:
            if p.required:
                errs.append(f"{where}: missing required parameter {p.pname!r}")
            continue
        v = args[p.pname]
        if v is None and not (isinstance(p.type, dict) and "optional" in p.type):
            errs.append(f"{where}.{p.pname}: null for non-optional type")
            continue
        prob = check(p.type, v, state.resolve_problem)
        if prob:
            errs.append(f"{where}.{p.pname}: {prob}")
    return errs


def call(spec, args: dict, state, view, bindings) -> Any:
    errs = check_params(spec.inputs, args, state, f"function {spec.rid}")
    if errs:
        raise InvalidRequest("; ".join(errs))
    impl = bindings.get("function", spec.impl_ref)
    out = impl(view, freeze(to_plain(dict(args))))
    is_opt = isinstance(spec.output, dict) and "optional" in spec.output
    try:
        plain = to_plain(out)
    except (TypeError, ValueError) as exc:
        raise FunctionOutputError(f"function {spec.rid} output is not a JSON value: {exc}") from None
    if plain is None:
        prob = None if is_opt else "returned None for a non-optional output"
    else:
        prob = check(spec.output, plain, state.resolve_problem)
    if prob:
        raise FunctionOutputError(f"function {spec.rid} output: {prob}")
    return freeze(plain)
