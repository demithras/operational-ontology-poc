"""Effect planning and dispatch.

create/update/delete/link/unlink on a local type -> canonical store ops (need a WriteGrant).
external_call, git_change and any import-qualified target -> an Adapter looked up by
(operation, target), falling back to (operation, "*"). Adapter interface (ENGINE_PREREG H20):
``apply(effect, payload) -> response`` and ``observations() -> iterable of dicts``; adapters never
see gates, policies or provenance.

Payload of effect i of action A: the ``payload`` binding "A#i" if bound; otherwise derived only when
derivation is unambiguous (fields named exactly like inputs; object key from the single input typed
``{"ref": target}``; link ends from the single inputs typed as each end). Else the package does not load.
Reserved payload keys: "$key" (update/delete object key), "$src"/"$dst" (link ends).
"""
from __future__ import annotations

from typing import Any, Optional

from .canon import freeze, to_plain

STORE_OPS = ("create", "update", "delete", "link", "unlink")
ADAPTER_OPS = ("external_call", "git_change")
KEY, SRC, DST = "$key", "$src", "$dst"


def _ref_inputs(inputs: list, t: str) -> list[str]:
    return [p["name"] for p in inputs if p["type"] == {"ref": t}]


def plan_effect(action: dict, eff: dict, model) -> tuple[str, Optional[dict]]:
    """(target_kind, derivation plan or None) for one IR effect."""
    op, tgt = eff["operation"], eff["target"]
    names = [p["name"] for p in action["inputs"]]
    fields = eff.get("fields")
    if op in ADAPTER_OPS or model.is_import(tgt):
        kind = "system" if op == "external_call" else ("import" if model.is_import(tgt) else
                                                       ("object_types" if model.get("object_types", tgt) else "link_types"))
        use = list(fields) if fields is not None else names
        return kind, ({"from_inputs": use} if all(f in names for f in use) else None)
    if op in ("create", "update", "delete"):
        kind = "object_types"
        if fields is not None and not all(f in names for f in fields):
            return kind, None
        if op == "create":
            pk = model.get("object_types", tgt).pk
            return kind, ({"from_inputs": list(fields)} if fields is not None and pk in fields else None)
        keyed = _ref_inputs(action["inputs"], tgt)
        if len(keyed) != 1 or (op == "update" and fields is None):
            return kind, None
        return kind, {"from_inputs": list(fields or []), "key_from": keyed[0]}
    spec = model.get("link_types", tgt)
    src, dst = _ref_inputs(action["inputs"], spec.src), _ref_inputs(action["inputs"], spec.dst)
    if len(src) != 1 or len(dst) != 1 or src[0] == dst[0] or (fields is not None and not all(f in names for f in fields)):
        return "link_types", None
    return "link_types", {"from_inputs": list(fields or []), "src_from": src[0], "dst_from": dst[0]}


def build_payload(action_spec, eff, inputs: dict, ctx, bindings) -> dict:
    key = f"{action_spec.rid}#{eff.index}"
    if bindings.has("payload", key):
        out = bindings.get("payload", key)(ctx)
        if not isinstance(out, dict):
            raise TypeError(f"payload binding {key!r} returned {type(out).__name__}, expected dict")
        return to_plain(out)
    plan = eff.plan
    payload = {f: inputs[f] for f in plan["from_inputs"] if f in inputs}
    for slot, src in ((KEY, "key_from"), (SRC, "src_from"), (DST, "dst_from")):
        if src in plan:
            payload[slot] = inputs.get(plan[src])
    return to_plain(payload)


def payload_problems(eff, payload: dict) -> list[str]:
    props = [k for k in payload if not k.startswith("$")]
    if eff.fields is not None and eff.target_kind in ("object_types", "link_types") and eff.operation in STORE_OPS:
        extra = [k for k in props if k not in eff.fields]
        if extra:
            return [f"effect {eff.index} writes undeclared fields {extra}"]
    return []


def store_op(eff, payload: dict, model, base_versions: dict) -> dict:
    props = {k: v for k, v in payload.items() if not k.startswith("$")}
    op, t = eff.operation, eff.target
    if op == "create":
        return {"op": op, "type": t, "key": props.get(model.get("object_types", t).pk), "props": props}
    if op in ("update", "delete"):
        k = payload.get(KEY)
        return {"op": op, "type": t, "key": k, "props": props, "expect": base_versions.get(repr((t, k)))}
    return {"op": op, "type": t, "src": payload.get(SRC), "dst": payload.get(DST), "props": props}


def routes_to_adapter(eff) -> bool:
    return eff.operation in ADAPTER_OPS or eff.target_kind == "import"


class AdapterRegistry:
    def __init__(self, adapters: Optional[dict] = None):
        self._by_key: dict[tuple[str, str], Any] = {}
        for (op, target), ad in (adapters or {}).items():
            self.register(op, target, ad)

    def register(self, operation: str, target: str, adapter: Any) -> None:
        if not (callable(getattr(adapter, "apply", None)) and callable(getattr(adapter, "observations", None))):
            raise TypeError("adapter must provide apply(effect, payload) and observations()")
        self._by_key[(operation, target)] = adapter

    def lookup(self, operation: str, target: str):
        return self._by_key.get((operation, target)) or self._by_key.get((operation, "*"))

    def all(self) -> list:
        return [self._by_key[k] for k in sorted(self._by_key)]


def effect_request(execution: str, action_spec, eff, idem_key: Optional[str]):
    return freeze({"execution": execution, "effect_id": f"{execution}/e{eff.index}", "operation": eff.operation,
                   "target": eff.target, "fields": list(eff.fields) if eff.fields is not None else None,
                   "action": action_spec.rid, "idempotency_key": idem_key})
