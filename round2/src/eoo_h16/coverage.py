"""Check the registered Domain 2 requirements against the project IR and the Engine-compiled model."""
from __future__ import annotations

from .requirements import registry


def _index(ir: dict) -> dict:
    return {k: {r["id"]: r for r in v} for k, v in ir.items() if isinstance(v, list) and k != "imports"}


def _referenced(ir: dict) -> dict:
    refs = {"policies": set(), "authority_rules": set()}
    for a in ir["actions"]:
        refs["policies"] |= {x.split(":", 1)[1] for x in a["policy_refs"]}
        refs["authority_rules"] |= {x.split(":", 1)[1] for x in a["authority_refs"]}
    return refs


def requirement_coverage(ir: dict, kernel_kinds: list[str], model) -> dict:
    """model = the Engine's compiled Model (``eoo_engine.registry.load_model(ir)``)."""
    ix, refs, rows = _index(ir), _referenced(ir), []
    for req in registry():
        problems, carriers = [], []
        for c in req["carriers"]:
            kind, rid = c[0], c[1]
            if kind == "property":
                obj = ix["object_types"].get(rid)
                ok = obj is not None and any(p["name"] == c[2] for p in obj["properties"])
                carriers.append({"kind": "object_types", "id": f"{rid}.{c[2]}", "present": ok, "compiled": ok and model.get("object_types", rid) is not None})
                if not ok:
                    problems.append(f"property {rid}.{c[2]} missing")
                continue
            r = ix.get(kind, {}).get(rid)
            present = r is not None
            compiled = present and model.get(kind, rid) is not None
            entry = {"kind": kind, "id": rid, "present": present, "compiled": compiled, "kernel_kind": kind in kernel_kinds}
            if kind in refs:
                entry["referenced_by_an_action"] = rid in refs[kind]
            if kind == "link_types" and present and len(c) > 2 and (r["from"], r["to"]) != c[2]:
                problems.append(f"link {rid} endpoints {r['from']}->{r['to']} != {c[2]}")
            if not (present and compiled and entry["kernel_kind"]):
                problems.append(f"{kind}:{rid} present={present} compiled={compiled}")
            carriers.append(entry)
        if req["id"] == "git:durable_actions_are_git_changes":
            bad = [a["id"] for a in ir["actions"] if any(e["operation"] != "git_change" for e in a["effects"])]
            if bad:
                problems.append(f"actions with non-git_change effects: {bad}")
        rows.append({"id": req["id"], "source": req["source"], "carriers": carriers, "ok": not problems, "problems": problems})
    unwired = sorted({f"{c['kind']}:{c['id']}" for r in rows for c in r["carriers"] if c.get("referenced_by_an_action") is False})
    return {"total": len(rows), "ok": sum(r["ok"] for r in rows), "failed": [r["id"] for r in rows if not r["ok"]],
            "coverage_fraction": (sum(r["ok"] for r in rows) / len(rows)) if rows else 0.0,
            "unwired_policy_or_authority_carriers": unwired, "requirements": rows}
