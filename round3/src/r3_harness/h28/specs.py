"""Frozen inputs of H28: ops/auth/systems per domain (project uses the H28 overlay, Q2/G4-E4), the combined systems document
for the single ExternalWorld process, the sysstate seed derived from the same frozen world, and the GEN-NULL operation (G4-E3)."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from r3_shared.extsystems import load_systems

ROUND3 = Path(__file__).resolve().parents[3]
DOMAINS = ("manufacturing", "project")
OPS_FILE = {"manufacturing": "spec/ops/manufacturing.json", "project": "spec/ops/project.h28.json"}
AUTH_FILE = {"manufacturing": "spec/authority/manufacturing.v3.json", "project": "spec/authority/project.h28.v3.json"}
GEN_OP = "record"
_cache: dict = {}


def load(domain: str) -> tuple[dict, dict, dict]:
    """(ops, auth, systems) deep copies."""
    if domain not in _cache:
        _cache[domain] = (json.loads((ROUND3 / OPS_FILE[domain]).read_text()), json.loads((ROUND3 / AUTH_FILE[domain]).read_text()),
                          load_systems(domain))
    return tuple(copy.deepcopy(x) for x in _cache[domain])


def combined_systems() -> dict:
    """ONE document for the ExternalWorld process serving both domains (per-case bindings carry the per-domain document)."""
    out = {"version": "r3-external-1", "domain": "combined", "window": 8, "systems": {}}
    for d in DOMAINS:
        doc = load_systems(d)
        out["window"] = doc["window"]
        for s, v in doc["systems"].items():
            if s in out["systems"] and out["systems"][s] != v:
                raise ValueError(f"system {s} declared differently in two domains")
            out["systems"][s] = v
    return out


def with_gen_null(ops: dict, auth: dict) -> tuple[dict, dict]:
    """GEN-NULL cases (G4-E3: the harness synthesises these effects): add ONE operation `record` whose only effect is an
    external GEN-NULL.record, plus an allow grant for every non-agent role holder. Deterministic; identical for the twin."""
    ops, auth = copy.deepcopy(ops), copy.deepcopy(auth)
    tpl = next(o for o in ops["operations"] if any(e.get("kind") == "external" for e in o["effects"]))
    op = copy.deepcopy(tpl)
    op.update(name=GEN_OP, summary="Record a generated (unobservable) external effect (H28 harness).", gated_inputs=["key"],
              immutable_after_authorization=["key"], inputs=[{"name": "key", "required": True, "type": "string"}],
              preconditions=[], business_rules=[], approval=None,
              effects=[{"kind": "external", "adapter": "GEN-NULL", "target": "record", "payload": {"key": {"input": "key"}}}],
              expected_outcome="GEN-NULL records the key (no observation path).")
    ops["operations"] = [o for o in ops["operations"] if o["name"] != GEN_OP] + [op]
    humans = [p["id"] for p in auth["principals"] if p["kind"] == "human" and p["roles"] and p["roles"] != ["none"]]
    for i, pid in enumerate(humans):
        auth["grants"].append({"id": f"h28-gen-null-{i}", "effect": "allow", "operation": GEN_OP, "origin": "neutral-extension",
                               "delegable": False, "principal": {"id": pid}, "resource": {"any": True}})   # `record` has no resource-typed input and GEN-NULL declares no resource type: the frozen `any` selector, never a "*" type
    return ops, auth


def sysstate_seed(domain: str, ops: dict) -> dict[tuple[str, str], dict]:
    """ExternalWorld starting state from the SAME frozen world (PROT note: targets exist in the external system)."""
    seed: dict = {}
    objs = {f"{o['type']}:{o['key']}": o["props"] for o in ops["seed"]["objects"]}
    links = ops["seed"]["links"]
    for ref, p in objs.items():
        t, k = ref.split(":", 1)
        if t == "PurchaseOrder":
            seed[("ERP", f"po:{k}")] = {"expectedAt": p.get("expectedAt"), "status": p.get("status")}
        elif t == "WorkOrder":
            seed[("MES", f"wo:{k}")] = {"plannedStart": p.get("plannedStart")}
        elif t == "InventoryLot":
            part = next((l["dst"].split(":", 1)[1] for l in links if l["src"] == ref and l["link_type"] == "PartReferencing_part"), None)
            wh = next((l["dst"].split(":", 1)[1] for l in links if l["src"] == ref and l["link_type"] == "InventoryLot_warehouse"), None)
            if part and wh:
                seed[("WMS", f"lot:{part}@{wh}")] = {"quantity": p.get("onHand")}
    return seed


def alt_targets(domain: str, systems: dict, ops: dict) -> dict[str, list[str]]:
    """Existing targets of each system (T1 'another existing target of S'): from the sysstate seed + target rules."""
    out: dict[str, list[str]] = {s: [] for s in systems["systems"]}
    for (s, k) in sysstate_seed(domain, ops):
        if s in out:
            out[s].append(k if not k.startswith("lot:") else f"transfer:{k[4:].split('@')[0]}@{k.split('@')[1]}->X")
    for s in out:
        out[s] = sorted(set(out[s]))
    return out
