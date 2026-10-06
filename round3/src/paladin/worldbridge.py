"""Bridge between the Engine and the r3_shared world store (the world file is canonical truth).

* `state_from_world`: rebuilds the Engine's State from the world at the start of every request (R6: preconditions and
  target existence are evaluated against the canonical world, never against a cache).
* `WorldExternalAdapter`: manufacturing `external_call` effects -> `WorldHandle(<system>).external_write` (WMS/ERP/MES);
  the payload is built from the ops spec effect declaration applied to the authorised inputs.
* `WorldGitAdapter`: project `git_change` effects -> canonical writes through the service handle (inside the request's
  world transaction, so a failed request rolls back).
"""
from __future__ import annotations

import json
from typing import Any, Callable

from paladin.engine.canon import to_plain
from paladin.engine.state import State
from r3_shared.world import WorldConflict


def split_ref(ref: str) -> tuple[str, str]:
    t, k = ref.split(":", 1)
    return t, k


def state_from_world(model, handle) -> State:
    """Engine State over the current world (objects with their versions, links without props)."""
    objects, links = {}, {}
    for t in model.all("object_types"):
        for row in handle.list(t):
            objects[(t, row["key"])] = {"props": row["props"], "ver": row["version"]}
    for lt in model.all("link_types"):
        for src, dst in handle.links(lt):
            links[(lt, split_ref(src), split_ref(dst))] = {"props": {}, "ver": 1}
    return State(model, objects, links)


def _eval_input(node: Any, inputs: dict) -> Any:
    if isinstance(node, dict) and "input" in node:
        return inputs.get(node["input"])
    if isinstance(node, dict) and "lit" in node:
        return node["lit"]
    raise ValueError(f"unsupported payload expression {node!r}")


class WorldExternalAdapter:
    """One external system (WMS | ERP | MES). Adapter interface per Engine H20: apply(effect, payload), observations()."""

    def __init__(self, system: str, handle_factory: Callable, effect_specs: dict, inputs_of: Callable[[str], dict]):
        self.system, self._handle, self._specs, self._inputs_of = system, handle_factory, effect_specs, inputs_of
        self._obs: list[dict] = []

    def apply(self, effect: Any, payload: Any) -> dict:
        spec = self._specs[effect["action"]]  # the ops-spec external effect of this action
        inputs = self._inputs_of(effect["execution"])
        body = to_plain({k: _eval_input(v, inputs) for k, v in spec["payload"].items()})
        self._handle(self.system).external_write(self.system, spec["target"], body, effect.get("idempotency_key"))
        rec = {"actionExecutionId": effect["execution"], "requestedQuantity": body.get("quantity"),
               "actualQuantity": body.get("quantity"), "transferStatus": "COMMITTED"}
        self._obs.append({"observation_type": self._otype(), "execution": effect["execution"], "data": self._data(rec, body)})
        return rec

    def _otype(self) -> str:
        return {"WMS": "WmsTransferRecordObserved", "ERP": "PurchaseOrderObserved", "MES": "WorkOrderObserved"}[self.system]

    def _data(self, rec: dict, body: dict) -> dict:
        if self.system == "WMS":
            return {k: rec[k] for k in ("transferStatus", "requestedQuantity", "actualQuantity")}
        # ERP/MES: the world's own post-effect truth for the touched record is the effect payload itself
        return self._after(body)

    def _after(self, body: dict) -> dict:
        h = self._handle("paladin-service")
        if self.system == "ERP":
            po = h.get("PurchaseOrder", body["po_id"]) or {"props": {}}
            old = po["props"].get("expectedAt")
            return {"expectedAt": (old - 1) if isinstance(old, int) else None}  # ERP shortens by one tick per expedite
        return {"plannedStart": body["new_planned_start"]}

    def observations(self):
        return list(self._obs)


class WorldGitAdapter:
    """Project canonical writes (`git_change` effects in the Round 2 IR) applied to the world through the service handle."""

    def __init__(self, handle):
        self._h, self._model = handle, None  # model attached after the Engine loads (`attach`)
        self._obs: list[dict] = []
        self._n = 0

    def attach(self, model) -> None:
        self._model = model

    def _expand(self, declared: str) -> list:
        return [declared] if declared in self._model.all("object_types") else sorted(self._model.implementers.get(declared, ()))

    def _find(self, types, key) -> str:
        hits = [t for t in types if self._h.get(t, key) is not None]
        if len(hits) != 1:
            raise WorldConflict(f"endpoint {key!r} does not resolve uniquely among {sorted(types)}")
        return f"{hits[0]}:{key}"

    def apply(self, effect: Any, payload: Any) -> dict:
        row, target = to_plain(dict(payload)), effect["target"]
        if "$src" in row:
            spec = self._model.get("link_types", target)
            src = self._find(self._expand(spec.src), row["$src"])
            dst = self._find(self._expand(spec.dst), row["$dst"])
            self._h.link(target, src, dst)
            stored = row
        else:
            key = row.get("$key", row.get("id"))
            props = {k: v for k, v in row.items() if not k.startswith("$")}
            cur = self._h.get(target, key)
            if cur is None:
                self._h.create(target, key, props)
            elif any(cur["props"].get(k) != v for k, v in props.items()):
                self._h.update(target, key, props)
            stored = {**row, **self._h.get(target, key)["props"]}
        self._n += 1
        sha = f"w{self._n:06d}"
        self._obs.append({"observation_type": "GitCommitObserved", "execution": effect["execution"],
                          "data": {"sha": sha}})
        return {"commit": sha, "parent": None, "target": target, "row": stored}

    def observations(self):
        return list(self._obs)


def jdump(x: Any) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"))
