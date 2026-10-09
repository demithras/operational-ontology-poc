"""Pure state-update functions of the external systems (P1f-3 `semantics`). External truth, not adapter logic: they replace
the domain rule hard-coded in paladin/worldbridge.py `_after`. Total: any payload shape yields an update, never an exception.
Signature: fn(get, target, payload) -> {state_key: props}; `get(key)` returns the current props dict ({} when absent)."""
from __future__ import annotations

from typing import Any, Callable


def _int(v: Any, default: int = 0) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) else default


def wms_transfer(get, target, payload):
    part, src, dst, q = payload.get("part"), payload.get("source"), payload.get("destination"), _int(payload.get("quantity"))
    log = get(f"{target}#log")
    out = {f"{target}#log": {"count": _int(log.get("count")) + 1, "quantity": q}}
    sk, dk = f"lot:{part}@{src}", f"lot:{part}@{dst}"
    out[sk] = {"quantity": _int(get(sk).get("quantity")) - q}
    out[dk] = {"quantity": _int(get(dk).get("quantity")) + q}
    return out


def erp_expedite(get, target, payload):
    key = f"po:{payload.get('po_id')}"
    return {key: {**get(key), "expectedAt": _int(get(key).get("expectedAt")) - 1}}


def mes_set_planned_start(get, target, payload):
    key = f"wo:{payload.get('work_order_id')}"
    return {key: {**get(key), "plannedStart": payload.get("new_planned_start")}}


def registry_publish(get, target, payload):
    return {target: {"published": _int(get(target).get("published")) + 1}}


def notify_set(get, target, payload):
    return {target: {"payload": dict(payload)}}


def gen_record(get, target, payload):
    return {target: {"count": _int(get(target).get("count")) + 1}}


SEMANTICS: dict[str, Callable] = {
    "wms_transfer": wms_transfer, "erp_expedite": erp_expedite, "mes_set_planned_start": mes_set_planned_start,
    "registry_publish": registry_publish, "notify_set": notify_set, "gen_record": gen_record,
}


def replay(systems: dict, applied: list[dict], seed: dict[tuple[str, str], dict] | None = None) -> dict[tuple[str, str], dict]:
    """Oracle-side replay of applied ledger rows (dicts with system, operation, target, payload) in seq order onto `seed`
    ({(system, key): props}). Returns the resulting {(system, key): props}."""
    state = {k: dict(v) for k, v in (seed or {}).items()}
    for r in applied:
        sem = systems["systems"][r["system"]]["operations"][r["operation"]]["semantics"]
        sysname = r["system"]
        upd = SEMANTICS[sem](lambda k, s=sysname: dict(state.get((s, k), {})), r["target"], r["payload"])
        for k, v in upd.items():
            state[(sysname, k)] = v
    return state
