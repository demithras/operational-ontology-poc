"""world_log grouping and snapshot replay (PROTOCOL-P1d P1d-1). Pure functions over WorldReader.log() rows: the
oracle rebuilds the world state of every commit point from the log alone and compares it with the real final snapshot
(an `unlogged_write` is a change the log does not explain). Reads no CallResult, imports no variant."""
from __future__ import annotations

CANON = ("create", "update", "delete", "link", "unlink", "external")


def group(rows: list[dict]) -> list[dict]:
    """One dict per transaction in commit order: {tx, tag, tick, first, writers, canon, marks, commit, authority}.
    `commit` = the `commit` mark row (or None); `authority` = list of `authority` mark rows."""
    out: dict[int, dict] = {}
    for r in rows:
        t = out.setdefault(r["tx"], {"tx": r["tx"], "tag": r["tag"], "tick": r["tick"], "first": r["seq"], "rows": [],
                                     "canon": [], "marks": [], "commit": None, "authority": [], "writers": set()})
        t["rows"].append(r)
        t["writers"].add(r["writer"])
        if r["kind"] == "mark":
            t["marks"].append(r)
            if r["ref"] == "commit" and t["commit"] is None:
                t["commit"] = r
            elif r["ref"] == "authority":
                t["authority"].append(r)
        elif r["kind"] in CANON:
            t["canon"].append(r)
    return sorted(out.values(), key=lambda t: t["first"])


def apply_rows(snap: dict, rows: list[dict]) -> dict:
    """New snapshot = `snap` + the canonical rows (shallow copies; values are replaced, never mutated)."""
    objs, links, effects = dict(snap["objects"]), [list(x) for x in snap["links"]], list(snap["effects"])
    for r in rows:
        k, d = r["kind"], r["data"]
        if k in ("create", "update"):
            objs[r["ref"]] = {"props": d["props"], "version": d["version"]}
        elif k == "delete":
            objs.pop(r["ref"], None)
        elif k == "link":
            x = [d["link_type"], d["src"], d["dst"]]
            if x not in links:
                links.append(x)
                links.sort()
        elif k == "unlink":
            x = [d["link_type"], d["src"], d["dst"]]
            if x in links:
                links.remove(x)
        elif k == "external":
            effects.append({"seq": d["effect_seq"], "adapter": d["adapter"], "target": d["target"],
                            "payload": d["payload"], "idempotency_key": d["idempotency_key"], "writer": r["writer"]})
    return {"objects": objs, "links": links, "effects": effects, "log_head": snap.get("log_head", 0)}


def same_world(a: dict, b: dict) -> bool:
    """Do two snapshots describe the same canonical world (objects incl. versions, links, external effects)?"""
    ext = lambda s: [(e["seq"], e["adapter"], e["target"], e["payload"], e["writer"]) for e in s["effects"]]  # noqa: E731
    return (a["objects"] == b["objects"] and sorted(map(tuple, a["links"])) == sorted(map(tuple, b["links"]))
            and ext(a) == ext(b))
