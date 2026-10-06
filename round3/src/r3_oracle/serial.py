"""Serial-order oracle for concurrent requests (PROT-H23-A8 R10).

simulate(...) applies a sequence of requests one after another to a CANONICAL snapshot using the oracle's own
ops_model (preconditions, authority, approvals consumed once, committed request_ids never commit twice) and returns
the resulting canonical world. judge(...) searches every serial order of the full request set (<= 24 orders for 4
requests) and then of every proper subset (requests the variant refused) for one whose final world equals the
measured final world. Imports r3_shared and r3_oracle only; reads the world store only through snapshots.
"""
from __future__ import annotations

import copy
import itertools
import json

from r3_shared.world import diff as world_diff

from . import approvals, ops_model


def canon_world(snap: dict) -> str:
    """Order-insensitive canonical form: object props, links, external effects (no seq/version/writer)."""
    objs = {k: v["props"] for k, v in sorted(snap["objects"].items())}
    links = sorted(tuple(x) for x in snap["links"])
    ext = sorted(json.dumps([e["adapter"], e["target"], e["payload"]], sort_keys=True, default=str)
                 for e in snap["effects"])
    return json.dumps([objs, links, ext], sort_keys=True, separators=(",", ":"), default=str)


def apply_records(snap: dict, records: list[dict]) -> dict:
    """Return a new snapshot with ops_model effect records applied."""
    out = {"objects": copy.deepcopy(snap["objects"]), "links": [list(x) for x in snap["links"]],
           "effects": list(snap["effects"])}
    for r in records:
        k = r["kind"]
        if k == "create":
            out["objects"].setdefault(r["ref"], {"props": copy.deepcopy(r["props"]), "version": 1})
        elif k == "update":
            cur = out["objects"].get(r["ref"])
            if cur is not None:
                for f, (_, nv) in r["changes"].items():
                    if nv is None:
                        cur["props"].pop(f, None)
                    else:
                        cur["props"][f] = nv
        elif k == "delete":
            out["objects"].pop(r["ref"], None)
        elif k == "link":
            t = r["ref"].split("|")
            if t not in out["links"]:
                out["links"].append(t)
        elif k == "unlink":
            t = r["ref"].split("|")
            if t in out["links"]:
                out["links"].remove(t)
        elif k == "external":
            out["effects"].append({"seq": len(out["effects"]) + 1, "adapter": r["adapter"], "target": r["target"],
                                   "payload": r["payload"], "writer": "oracle", "idempotency_key": None})
    return out


def simulate(ops_spec: dict, auth_spec: dict, snap0: dict, now: int, requests: list[dict], order,
             approvals_budget: dict | None = None) -> tuple[dict, list[str]]:
    """requests: [{subject, obo, op, args, rid}]. Returns (final snapshot, per-request outcome kinds)."""
    snap, committed, kinds = snap0, set(), []
    budget = dict(approvals_budget or {})
    for i in order:
        q = requests[i]
        key = approvals.key(q["subject"], q.get("obo"), q["op"], q["args"])
        out = ops_model.evaluate(ops_spec, auth_spec, q["subject"], q.get("obo"), q["op"], q["args"], snap, now,
                                 frozenset(committed), q.get("rid"), approved=budget.get(key, 0) > 0)
        kinds.append(out.kind if out.effects or out.kind != ops_model.COMMIT else "COMMIT_NOEFFECT")
        if out.kind == ops_model.COMMIT and out.effects:
            if out.used_approval:
                budget[key] = budget.get(key, 0) - 1
            snap = apply_records(snap, out.effects)
            if q.get("rid"):
                committed.add(q["rid"])
    return snap, kinds


def judge(ops_spec: dict, auth_spec: dict, snap0: dict, now: int, requests: list[dict], final: dict,
          approvals_budget: dict | None = None) -> dict:
    """{'match': 'full'|'subset'|None, 'order': [...], 'subset': [...], 'serial_orders_tried': n}.
    A full-set match is preferred; a subset match means the variant refused the others (a progress question)."""
    want, n, tried = canon_world(final), len(requests), 0
    for size in range(n, 0, -1):
        for subset in itertools.combinations(range(n), size):
            for order in itertools.permutations(subset):
                tried += 1
                got, _ = simulate(ops_spec, auth_spec, snap0, now, requests, order, approvals_budget)
                if canon_world(got) == want:
                    return {"match": "full" if size == n else "subset", "order": list(order),
                            "subset": list(subset), "serial_orders_tried": tried}
    got, _ = simulate(ops_spec, auth_spec, snap0, now, requests, (), approvals_budget)
    if canon_world(got) == want:
        return {"match": "subset", "order": [], "subset": [], "serial_orders_tried": tried}
    return {"match": None, "order": [], "subset": [], "serial_orders_tried": tried}


def distinct_finals(ops_spec, auth_spec, snap0, now, requests, approvals_budget=None) -> set[str]:
    return {canon_world(simulate(ops_spec, auth_spec, snap0, now, requests, o, approvals_budget)[0])
            for o in itertools.permutations(range(len(requests)))}


__all__ = ["canon_world", "apply_records", "simulate", "judge", "distinct_finals", "world_diff"]
