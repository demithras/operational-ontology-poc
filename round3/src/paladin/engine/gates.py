"""Gate evaluation shared by every action: identity, inputs, authority, preconditions, policies.

Logic exceptions or non-boolean results fail closed (the gate fails, the detail names the error).
"""
from __future__ import annotations

from typing import Any

from .authority import Principal, Resource
from .canon import freeze
from .capabilities import ReadOnly
from .functions import check_params
from .typecheck import check, ref_values

DENY, APPROVAL, ALLOW, CLASSIFY = "deny", "require_approval", "allow", "classify"


def bool_logic(fn, ctx) -> bool:
    out = fn(ctx)
    if not isinstance(out, bool):
        raise TypeError(f"logic returned {type(out).__name__}, expected bool")
    return out


def gate(name: str, passed: bool, detail: Any = None) -> dict:
    return {"gate": name, "passed": passed, "detail": detail}


def make_ctx(eng, spec, rec: dict, state=None, **extra) -> ReadOnly:
    """Read-only context handed to precondition / policy / constraint / outcome / payload logic."""
    st = state if state is not None else eng.state()
    view = eng.read_view(st)

    def call(fid: str, args: dict | None = None):
        return eng.dispatch("functions", "call", fid, args=dict(args or {}), state=st, view=view)

    base = dict(package_id=eng.model.package_id, package_version=eng.model.version, action=spec.rid,
                action_version=spec.version, execution=rec["exec"], inputs=freeze(rec["inputs"]),
                principal=Principal.from_plain(rec["principal"]),  # P2a patch V2: the presented (possibly delegated) principal
                view=view, call=call, now=rec["updated_at"],
                planned=(), observations=(), responses=())
    base.update({k: freeze(v) for k, v in extra.items()})
    return ReadOnly(**base)


def resources_of(eng, spec, inputs: dict) -> tuple:
    st, out = eng.state(), []
    for p in spec.inputs:
        if p.pname not in inputs:
            continue
        for declared, key in ref_values(p.type, inputs[p.pname]):
            hits = st.locate(declared, key) if not eng.model.is_import(declared) else [(declared, key)]
            out += [Resource(declared, key, actual) for actual, _ in hits]
    out += [Resource(e.target, None, e.target) for e in spec.effects]
    return tuple(out)


class _NoExistence:
    """State stand-in whose references always resolve: input problems minus target existence (G3-E17)."""
    @staticmethod
    def resolve_problem(declared, key):
        return None


def check_inputs(eng, spec, inputs: Any, existence: bool = True) -> list[str]:
    """Input problems; existence=False leaves out 'the referenced object does not exist' (checked after the deny rules)."""
    return check_params(spec.inputs, inputs, eng.state() if existence else _NoExistence, f"action {spec.rid}")


def run_logic_gate(name: str, items: list, ctx) -> dict:
    """items: [(label, callable)] each must return True."""
    failed, errors = [], []
    for label, fn in items:
        try:
            if not bool_logic(fn, ctx):
                failed.append(label)
        except Exception as exc:
            errors.append(f"{label}: {type(exc).__name__}: {exc}")
    return gate(name, not failed and not errors, {"failed": failed, "errors": errors})


def evaluate_policies(eng, spec, ctx) -> tuple[str, dict]:
    """deny > require_approval > allow; referencing allow policies => default deny if none applies."""
    results, errors, classified, deny_errors = [], [], [], []
    for text, pid in spec.policy_refs:
        try:
            if pid is None:
                d = eng.bindings.get("policy_import", text)(ctx)
                if d not in (DENY, APPROVAL, ALLOW, CLASSIFY, None):
                    raise TypeError(f"policy_import binding returned {d!r}")
                results.append({"ref": text, "decision": d, "applies": d is not None, "version": None})
                continue
            pol = eng.model.get("policies", pid)
            applies = eng.dispatch("policies", "evaluate", pid, ctx=ctx)
            results.append({"ref": text, "decision": pol.decision, "applies": applies, "version": pol.version})
            if pol.decision == CLASSIFY and applies:
                classified.append(pid)
        except Exception as exc:
            errors.append(f"{text}: {type(exc).__name__}: {exc}")
            pol_obj = eng.model.get("policies", pid) if pid is not None else None
            if pol_obj is not None and pol_obj.decision == DENY:   # V4: a deny rule that cannot be evaluated fails closed
                deny_errors.append(text)
    applying = {r["decision"] for r in results if r["applies"]}
    allow_declared = any(r["decision"] == ALLOW and r["version"] is not None for r in results)
    if errors or DENY in applying:
        verdict = "DENIED"
    elif APPROVAL in applying:
        verdict = "PENDING_APPROVAL"
    elif allow_declared and ALLOW not in applying:
        verdict = "DENIED"
    else:
        verdict = "APPROVED"
    detail = {"results": results, "errors": errors, "deny_errors": deny_errors, "classified": classified,
              "default_deny": allow_declared and ALLOW not in applying and not errors and DENY not in applying
              and APPROVAL not in applying}
    return verdict, gate("policy", verdict != "DENIED", detail)


def observation_problems(eng, spec, data: Any) -> list[str]:
    if not hasattr(data, "items"):
        return ["observation data must be a mapping"]
    errs = [f"undeclared property {k!r}" for k in data if k not in spec.props]
    for k, p in spec.props.items():
        if k not in data or data[k] is None:
            if p["required"]:
                errs.append(f"missing required property {k!r}")
            continue
        prob = check(p["type"], data[k], eng.state().resolve_problem)
        if prob:
            errs.append(f"{k}: {prob}")
    return errs
