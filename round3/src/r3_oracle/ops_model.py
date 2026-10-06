"""Pure model of the neutral ops-spec semantics (spec/ops/<domain>.json) plus the effective-authority rule.

evaluate(...) -> Outcome: what a CORRECT system must do for one request against a canonical snapshot:
the verdict class and the exact expected effect records. Imports r3_shared and r3_oracle only; cites the spec,
never any variant. Prose-defined helpers come from helpers.py.
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field

from r3_shared.world import diff as world_diff

from . import authority
from .expr import Ctx, ev
from .view import HelperError, View, rid

COMMIT, DENIED_AUTHORITY, DENIED_RULE, INVALID, NEEDS_APPROVAL, UNKNOWN_OP = (
    "COMMIT", "DENIED_AUTHORITY", "DENIED_RULE", "INVALID", "NEEDS_APPROVAL", "UNKNOWN_OP")
LOOSE_PROPS = {"Verdict": {"reason", "derivation_hash"}}  # prose fixes the inputs but not the exact text/layout


@dataclass
class Outcome:
    kind: str
    effects: list[dict] = field(default_factory=list)
    detail: str = ""
    extras: list[str] = field(default_factory=list)  # args keys outside the operation's schema
    error: str | None = None  # the ORACLE itself failed on this input (fail closed; makes the run INVALID)

    @property
    def commits(self) -> bool:
        return self.kind == COMMIT and bool(self.effects)


def op_of(ops_spec: dict, name: str) -> dict | None:
    return next((o for o in ops_spec["operations"] if o["name"] == name), None)


def validate_args(op: dict, args) -> tuple[bool, str, list[str]]:
    if not isinstance(args, dict):
        return False, "args not an object", []
    names = {i["name"] for i in op["inputs"]}
    extras = sorted(k for k in args if k not in names)
    for i in op["inputs"]:
        val = args.get(i["name"])
        if val is None:
            if i["required"]:
                return False, f"missing {i['name']}", extras
            continue
        t = i["type"]
        if t == "integer" and (not isinstance(val, int) or isinstance(val, bool)):
            return False, f"{i['name']} not integer", extras
        if t in ("string", "resource") and not isinstance(val, str):
            return False, f"{i['name']} not string", extras
        if t == "resource" and val.strip() == "":
            return False, f"{i['name']} blank resource id", extras
    return True, "", extras


def resources_of(op: dict, args: dict) -> list[tuple[str, str]]:
    return [(i["resource_type"], args[i["name"]]) for i in op["inputs"]
            if i["type"] == "resource" and isinstance(args.get(i["name"]), str) and args[i["name"]]]


def _link_types(ops_spec: dict) -> dict[str, tuple[str, str]]:
    return {lt["name"]: (lt["from"], lt["to"]) for lt in ops_spec["link_types"]}


def _plain(x):
    return x[1] if isinstance(x, tuple) else x


def _as_ref(x, type_: str):
    return x if isinstance(x, tuple) else (type_, x)


def expected_diff(ops_spec: dict, op: dict, ctx: Ctx, snapshot: dict) -> list[dict]:
    """Apply the op's declared effects to a copy of the snapshot (all expressions read the PRE state)."""
    lts = _link_types(ops_spec)
    after = {"objects": copy.deepcopy(snapshot["objects"]), "links": [list(x) for x in snapshot["links"]],
             "effects": []}
    externals: list[dict] = []
    for e in op["effects"]:
        k = e["kind"]
        if k == "external":
            payload = {pk: _plain(ev(pv, ctx)) for pk, pv in e["payload"].items()}
            externals.append({"kind": "external", "adapter": e["adapter"], "target": e["target"], "payload": payload})
        elif k in ("create", "update"):
            ref = _as_ref(ev(e["key"], ctx), e["type"])
            props = {pk: ev(pv, ctx) for pk, pv in e["props"].items()}
            props = {pk: pv for pk, pv in props.items() if pv is not None}
            cur = after["objects"].get(rid(ref))
            if k == "create" and cur is None:
                after["objects"][rid(ref)] = {"props": props, "version": 1}
            elif k == "update" and cur is not None:
                cur["props"].update(props)
        elif k in ("link", "unlink"):
            lt = e["link_type"]
            s, d = (_as_ref(ev(e[x], ctx), lts[lt][i]) for i, x in enumerate(("src", "dst")))
            triple = [lt, rid(s), rid(d)]
            if k == "link" and triple not in after["links"]:
                after["links"].append(triple)
            if k == "unlink" and triple in after["links"]:
                after["links"].remove(triple)
        else:
            raise HelperError(f"unknown effect kind {k}")
    return world_diff(snapshot | {"effects": []}, after) + externals


def evaluate(ops_spec: dict, auth_spec: dict, subject: str, on_behalf_of: str | None, operation: str, args,
             snapshot: dict, now: int, committed_ids: frozenset = frozenset(), request_id: str | None = None
             ) -> Outcome:
    op = op_of(ops_spec, operation)
    if op is None:
        return Outcome(UNKNOWN_OP, detail="not an operation of the spec")
    ok, why, extras = validate_args(op, args)
    if not ok:
        return Outcome(INVALID, detail=why, extras=extras)
    dec = authority.decide(subject, on_behalf_of, operation, resources_of(op, args), auth_spec)
    if not dec.allow:
        return Outcome(DENIED_AUTHORITY, detail=dec.reason, extras=extras)
    if request_id is not None and request_id in committed_ids:
        return Outcome(COMMIT, [], "replay of a committed request_id: no second effect", extras)
    actor = authority.actor_for_rules(subject, on_behalf_of, auth_spec)
    view = View(snapshot, now, authority.relations_of(auth_spec, actor), ops_spec.get("config"))
    ctx = Ctx(op, args, view)
    try:
        for r in op["business_rules"]:
            if r["decision"] == "deny" and ev(r["when"], ctx):
                return Outcome(DENIED_RULE, detail=r["id"], extras=extras)
        for p in op["preconditions"]:
            if not ev(p["predicate"], ctx):
                return Outcome(INVALID, detail=f"precondition {p['id']}", extras=extras)
        for r in op["business_rules"]:
            if r["decision"] == "require_approval" and ev(r["when"], ctx):
                return Outcome(NEEDS_APPROVAL, detail=r["id"], extras=extras)
        return Outcome(COMMIT, expected_diff(ops_spec, op, ctx, snapshot), "", extras)
    except HelperError as exc:
        return Outcome(DENIED_RULE, detail=f"helper error (fail closed): {exc}", extras=extras)
    except Exception as exc:  # noqa: BLE001 - an oracle bug must be visible, never silently pass
        return Outcome(DENIED_RULE, detail="oracle error", extras=extras, error=f"{type(exc).__name__}: {exc}")


# -- record matching (expected vs measured) ------------------------------------------------------------
def _canon(x) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"), default=str)


def _norm(rec: dict) -> str:
    k = rec["kind"]
    if k == "external":
        ref = rec.get("ref")
        if ref and "adapter" not in rec:
            adapter, rest = ref.split(":", 1)
            rec = {**rec, "adapter": adapter, "target": rest.rsplit("#", 1)[0]}
        return _canon(["external", rec["adapter"], rec["target"], rec["payload"]])
    if k == "create":
        t = rec["ref"].split(":", 1)[0]
        props = dict(rec["props"])
        for lp in LOOSE_PROPS.get(t, ()):
            val = props.get(lp)
            good = isinstance(val, str) and val.strip() != "" and (lp != "derivation_hash"
                                                                   or re.fullmatch(r"[0-9a-f]{64}", val))
            if good:
                props[lp] = "<loose>"
        return _canon(["create", rec["ref"], props])
    if k == "update":
        ch = {f: [a, b] for f, (a, b) in rec["changes"].items()}
        return _canon(["update", rec["ref"], ch])
    if k == "delete":
        return _canon(["delete", rec["ref"]])
    return _canon([k, rec["ref"]])


def match_records(expected: list[dict], measured: list[dict]) -> tuple[list[dict], list[dict]]:
    """Multiset comparison. Returns (unexpected_measured, missing_expected)."""
    pool = [(_norm(r), r) for r in expected]
    unexpected = []
    for m in measured:
        key = _norm(m)
        for i, (k, _) in enumerate(pool):
            if k == key:
                pool.pop(i)
                break
        else:
            unexpected.append(m)
    return unexpected, [r for _, r in pool]
