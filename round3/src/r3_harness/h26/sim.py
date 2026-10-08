"""Pure snapshot helpers for the pair generator's oracle pre-simulation (no variant, no world store)."""
from __future__ import annotations

import copy


def empty() -> dict:
    return {"objects": {}, "links": [], "effects": [], "log_head": 0}


def apply_changes(snap: dict, changes: list[dict]) -> dict:
    """Seed-batch changes ({"op": create|update|delete|link|unlink, ...}) applied to a copy of the snapshot."""
    s = copy.deepcopy(snap)
    for c in changes:
        op = c["op"]
        if op == "create":
            s["objects"][f"{c['type']}:{c['key']}"] = {"props": dict(c["props"]), "version": 1}
        elif op == "update":
            o = s["objects"].get(f"{c['type']}:{c['key']}")
            if o is not None:
                o["props"].update(c["props"])
        elif op == "delete":
            s["objects"].pop(f"{c['type']}:{c['key']}", None)
        elif op == "link":
            t = [c["link_type"], c["src"], c["dst"]]
            if t not in s["links"]:
                s["links"].append(t)
        elif op == "unlink":
            t = [c["link_type"], c["src"], c["dst"]]
            if t in s["links"]:
                s["links"].remove(t)
    return s


def apply_effects(snap: dict, effects: list[dict]) -> dict:
    """Oracle effect records (r3_shared.world.diff form) applied to a copy of the snapshot."""
    s = copy.deepcopy(snap)
    for e in effects:
        k = e["kind"]
        if k == "create":
            s["objects"][e["ref"]] = {"props": dict(e["props"]), "version": 1}
        elif k == "update" and e["ref"] in s["objects"]:
            s["objects"][e["ref"]]["props"].update({f: v[1] for f, v in e["changes"].items()})
        elif k == "delete":
            s["objects"].pop(e["ref"], None)
        elif k == "link":
            t = e["ref"].split("|", 2)
            if t not in s["links"]:
                s["links"].append(t)
        elif k == "unlink":
            t = e["ref"].split("|", 2)
            if t in s["links"]:
                s["links"].remove(t)
    return s


def seed_batches(ops: dict) -> list[list[dict]]:
    """The domain seed as two equal-shape batches (objects, links)."""
    objs = [{"op": "create", "type": o["type"], "key": o["key"], "props": o["props"]} for o in ops["seed"]["objects"]]
    lks = [{"op": "link", "link_type": l["link_type"], "src": l["src"], "dst": l["dst"]} for l in ops["seed"]["links"]]
    return [objs, lks]
