"""Generate legal mixed-domain IR packages from the REAL manufacturing and project IRs plus cross-domain declarations.

Variants: ``merged_local`` (one package holding pruned subsets of both domains + cross-domain links / properties /
interface implementations / functions / actions as ordinary resources), ``import_project`` / ``import_manufacturing``
(one domain's subset importing the other package and referring to it by ``<import>#<name>`` references).
Everything is a plain IR package: the generator knows nothing the validator and Engine do not.
"""
from __future__ import annotations

import copy
import json
import random

from eoo_exp.util import ROOT
from eoo_ir import validate

KINDS = ("object_types", "link_types", "interfaces", "functions", "actions", "policies", "authority_rules",
         "observation_types", "constraints")
IMPORT_OF = {"manufacturing": "manufacturing-ontology", "project": "project-ontology"}
COLLISION = {"Decision": "ProjectDecision"}  # the only id both real domains declare (object type)
_BASE: dict = {}


def _rename(x, mapping):
    if isinstance(x, dict):
        return {k: _rename(v, mapping) for k, v in x.items()}
    if isinstance(x, list):
        return [_rename(v, mapping) for v in x]
    if isinstance(x, str):
        for old, new in mapping.items():
            if x == old or x.startswith(old + ".") or x.startswith(old + ":"):
                return new + x[len(old):]
    return x


def bases() -> dict:
    if not _BASE:
        m = json.loads((ROOT / "domains/manufacturing/ir.json").read_text())
        p = json.loads((ROOT / "domains/project/ir.v2.json").read_text())
        _BASE.update({"manufacturing": m, "project": p, "project_renamed": _rename(p, COLLISION)})
    return _BASE


def origin_ids(pkg_name: str) -> dict:
    b = bases()["project_renamed" if pkg_name == "project" else pkg_name]
    return {k: {r["id"] for r in b[k]} for k in KINDS}


def prune(pkg: dict, max_rounds: int = 60) -> tuple[dict, int]:
    """Drop every resource a validation error points at, until the package validates. Returns (pkg, rounds)."""
    for rounds in range(max_rounds):
        errs = validate(pkg)
        if not errs:
            return pkg, rounds
        drop: dict = {}
        for e in errs:
            head = e.path.split(".")[0]
            if "[" not in head:
                raise ValueError(f"unprunable error {e}")
            kind, idx = head[:-1].split("[")
            drop.setdefault(kind, set()).add(int(idx))
        for kind, idxs in drop.items():
            pkg[kind] = [r for i, r in enumerate(pkg[kind]) if i not in idxs]
    raise ValueError("prune did not converge")


def subset(base: dict, rnd: random.Random, keep: float) -> dict:
    out = {k: v for k, v in base.items() if k not in KINDS}
    for k in KINDS:
        out[k] = [copy.deepcopy(r) for r in base[k] if rnd.random() < keep]
    return out


def _card(rnd):
    return {"min": rnd.choice([0, 0, 1]), "max": rnd.choice([1, 2, "*"])}


def _uid(rnd, tag):
    return f"x-{tag}-{rnd.randrange(10 ** 6)}"


def cross_resources(pkg: dict, rnd: random.Random, left: list, right: list, other_pkg_id: str | None) -> dict:
    """Cross-domain declarations. left/right = type refs ("Type" or "<import>#Type") of the two sides."""
    added: dict = {k: [] for k in KINDS}
    if not left or not right:
        return added
    for n in range(rnd.randint(1, 4)):
        a, b = (rnd.choice(left), rnd.choice(right))
        a, b = (a, b) if rnd.random() < 0.5 else (b, a)
        added["link_types"].append({"id": _uid(rnd, f"link{n}"), "from": a, "to": b, "from_cardinality": _card(rnd),
                                    "to_cardinality": _card(rnd), "directed": rnd.random() < 0.7, "properties": []})
    for n in range(rnd.randint(0, 2)):  # a property typed by the other domain's object type
        target = rnd.choice(pkg["object_types"]) if pkg["object_types"] else None
        if target is not None:
            te = {"ref": rnd.choice(right)}
            te = rnd.choice([te, {"optional": te}, {"list": te}])
            target["properties"].append({"name": f"xref_{n}_{rnd.randrange(10 ** 5)}", "type": te, "required": False})
    if rnd.random() < 0.6:  # cross-domain function: inputs from both sides, reads a local property
        reads = [f"{o['id']}.{o['properties'][0]['name']}" for o in pkg["object_types"][:1] if o["properties"]]
        added["functions"].append({"id": _uid(rnd, "fn"), "inputs": [
            {"name": "a", "type": {"ref": rnd.choice(left)}, "required": True},
            {"name": "b", "type": {"ref": rnd.choice(right)}, "required": True}], "output": "boolean",
            "purity": "NO_COMMITTED_BUSINESS_SIDE_EFFECT", "reads": reads, "implementation_ref": _uid(rnd, "impl"),
            "determinism": "deterministic"})
    if rnd.random() < 0.7:  # cross-domain action: git_change on a local type, refs from both sides, both authorities
        auth = [f"auth:{r['id']}" for r in rnd.sample(pkg["authority_rules"], min(2, len(pkg["authority_rules"])))]
        if other_pkg_id:
            auth.append(f"{other_pkg_id}#{_uid(rnd, 'rule')}")
        pol = [f"policy:{r['id']}" for r in rnd.sample(pkg["policies"], min(2, len(pkg["policies"])))]
        if other_pkg_id and rnd.random() < 0.5:
            pol.append(f"{other_pkg_id}#{_uid(rnd, 'policy')}")
        loc = pkg["object_types"][0]["id"] if pkg["object_types"] else None
        effects = [{"target": rnd.choice(["wms", "git-remote"]), "operation": "external_call"}]
        if loc:
            effects.append({"target": loc, "operation": "git_change"})
        added["actions"].append({"id": _uid(rnd, "act"), "inputs": [
            {"name": "left", "type": {"ref": rnd.choice(left)}, "required": True},
            {"name": "right", "type": {"ref": rnd.choice(right)}, "required": rnd.random() < 0.5}],
            "authority_refs": auth, "policy_refs": pol, "preconditions": ["cross-domain precondition"],
            "effects": effects, "idempotency": rnd.choice(["required", "not_applicable"]),
            "outcome_predicate": "cross-domain outcome", "compensation_action": None, "version": "x1"})
    return added


def _merge_cross(pkg: dict, added: dict) -> None:
    for k in KINDS:
        pkg[k] += added[k]


def build_mixed(rnd: random.Random) -> tuple[dict, dict]:
    """One mixed-domain package + metadata (variant, per-domain origin counts, cross resources, prune rounds)."""
    b = bases()
    variant = rnd.choice(["merged_local", "merged_local", "import_project", "import_manufacturing"])
    keep_m, keep_p = rnd.uniform(0.35, 1.0), rnd.uniform(0.35, 1.0)
    if variant == "merged_local":
        m, p = subset(b["manufacturing"], rnd, keep_m), subset(b["project_renamed"], rnd, keep_p)
        pkg = {"package_id": "mixed-ontology", "domain_id": "mixed", "version": f"g{rnd.randrange(10 ** 6)}",
               "imports": [], "metadata": {"generated": True}, **{k: m[k] + p[k] for k in KINDS}}
        pkg, rounds = prune(pkg)
        mt = [o["id"] for o in pkg["object_types"] if o["id"] in origin_ids("manufacturing")["object_types"]]
        pt = [o["id"] for o in pkg["object_types"] if o["id"] in origin_ids("project")["object_types"]]
        added = cross_resources(pkg, rnd, mt, pt, None)
        for iface in pkg["interfaces"] if rnd.random() < 0.5 else []:  # a type implements a foreign-domain interface
            tgt = rnd.choice(pkg["object_types"]) if pkg["object_types"] else None
            if tgt is not None and iface["id"] not in tgt["implements"]:
                tgt["implements"].append(iface["id"])
    else:
        mine, other = ("project", "manufacturing") if variant == "import_project" else ("manufacturing", "project")
        own = subset(b["project_renamed" if mine == "project" else mine], rnd, keep_p if mine == "project" else keep_m)
        pkg = {**{k: v for k, v in own.items()}, "imports": [IMPORT_OF[other]], "version": f"g{rnd.randrange(10 ** 6)}"}
        pkg["metadata"] = {"generated": True}
        pkg, rounds = prune(pkg)
        imp = IMPORT_OF[other]
        foreign = [f"{imp}#{o['id']}" for o in b["project_renamed" if other == "project" else other]["object_types"]]
        local = [o["id"] for o in pkg["object_types"]]
        added = cross_resources(pkg, rnd, local, rnd.sample(foreign, min(len(foreign), 4)), imp)
    _merge_cross(pkg, added)
    pkg, rounds2 = prune(pkg)
    return pkg, {"variant": variant, "prune_rounds": rounds + rounds2,
                 "cross_added": {k: len(v) for k, v in added.items() if v}}


def origin_counts(pkg: dict) -> dict:
    """Resources per origin: manufacturing / project (by id match to the real IRs) / generated (cross)."""
    out = {"manufacturing": 0, "project": 0, "generated": 0}
    mi, pi = origin_ids("manufacturing"), origin_ids("project")
    for k in KINDS:
        for r in pkg[k]:
            out["manufacturing" if r["id"] in mi[k] else "project" if r["id"] in pi[k] else "generated"] += 1
    return out


def imports_domain(pkg: dict) -> bool:
    s = json.dumps(pkg)
    return any(imp + "#" in s for imp in pkg.get("imports", []))
