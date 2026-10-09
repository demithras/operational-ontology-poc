"""Observation-independence topology (P1f-5; PROT-H28 R28-9): the action path and the observation path must share no key, no
connection, no process-owned object. Computed from the binding the harness built; any shared element -> shared_trust_root true ->
the contract's inconclusive_if. Identifies objects by identity, never by name."""
from __future__ import annotations

import hashlib

from r3_shared import extcap


def _kid(s: str) -> str:
    return hashlib.sha256(str(s).encode()).hexdigest()[:12]


def _held(o) -> list:
    return [v for v in getattr(o, "__dict__", {}).values()]


def check(binding, data_socket: str, dep_id: str) -> dict:
    """Per system: action path {adapter_id, cap root id, socket} vs observation path {observer key id, db mode, process}."""
    obs = binding.observer
    obs_key, obs_path = getattr(obs, "_key", ""), getattr(obs, "_path", "")
    obs_held = [id(v) for v in _held(obs)]
    out = {"deployment": dep_id, "systems": {}, "shared_trust_root": False, "reasons": []}
    for s, ad in binding.adapters.items():
        inner = getattr(ad, "inner", ad)
        client = getattr(inner, "client", None)
        root = binding.root_caps.get(s, "")
        act = {"adapter_id": getattr(ad, "adapter_id", "?"), "cap_root_id": _kid(extcap.root_nonce(root)) if root else None,
               "socket": getattr(client, "_sock", data_socket)}
        ob = {"observer_key_id": _kid(obs_key), "db_open_mode": "ro", "db_path": obs_path, "connection": "own sqlite connection"}
        why = []
        if obs_key and (obs_key == root or (root and obs_key in root) or (root and root in obs_key)):
            why.append("observer key is (derived from) the action root cap")
        if act["socket"] and act["socket"] == obs_path:
            why.append("observer reads through the action socket")
        if client is not None and (id(client) in obs_held or obs is client):
            why.append("observer holds the adapter's client object")
        if any(id(v) in obs_held for v in _held(client) if v is not None and not isinstance(v, (str, int, float, bool, type(None)))):
            why.append("observer and adapter client share a process-owned object")
        if act["cap_root_id"] and act["cap_root_id"] == ob["observer_key_id"]:
            why.append("observer key id equals cap root id")
        out["systems"][s] = {"action": act, "observation": ob, "shared_trust_root": bool(why), "why": why}
        if why:
            out["shared_trust_root"] = True
            out["reasons"] += [f"{s}: {w}" for w in why]
    return out
