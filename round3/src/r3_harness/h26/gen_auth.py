"""Authority-spec perturbation for the pair generator: 2-8 fresh principals and 2-6 generated disclosure rules
(PROT-H26 B2). Every spec is validated with r3_shared.authspec.validate_strict; never raises (falls back to the base)."""
from __future__ import annotations

import copy
import random

from r3_shared.authspec import validate_strict


def roles_of(auth: dict) -> list[str]:
    return sorted({r for p in auth["principals"] for r in p["roles"]} | {"nobody-role"})


def gen_rule(rng: random.Random, ops: dict, auth: dict, n: int) -> dict:
    types = {t["name"]: [f["name"] for f in t["fields"]] for t in ops["resource_types"]}
    pub = set(auth["disclosure"]["public_types"])
    t = rng.choice(sorted(set(types) - pub) or sorted(types))
    ft = lambda l: l.get("from_types") or [l["from"]]  # noqa: E731
    tt = lambda l: l.get("to_types") or [l["to"]]  # noqa: E731
    lts = [l for l in ops["link_types"] if t in ft(l) + tt(l)]
    sel = rng.choice([{"any": True}, {"role": rng.choice(roles_of(auth))}, {"role": rng.choice(roles_of(auth))}])
    via = None
    if lts and rng.random() < 0.45:
        l = rng.choice(lts)
        out = t in ft(l)
        via = {"link": l["name"], "dir": "out" if out else "in", "type": rng.choice(tt(l) if out else ft(l))}
    deny = rng.random() < 0.18
    fl = types[t]
    fields = "*" if (not deny and rng.random() < 0.2) else sorted(rng.sample(fl, rng.randint(0, len(fl))))
    links = sorted({l["name"] for l in rng.sample(lts, rng.randint(0, len(lts)))}) if lts else []
    return {"id": f"gen-{n}", "effect": "deny" if deny else "allow", "principal": sel,
            "object": {"type": t, "keys": None, "via": via},
            "reveals": {"exists": (rng.random() < 0.9) if not deny else False, "fields": fields, "links": links,
                        "provenance": rng.choice(["none", "own", "scalars", "actors"]) if not deny else "none"}}


def perturb(rng: random.Random, ops: dict, base: dict, tag: str) -> dict:
    for _ in range(8):
        a = copy.deepcopy(base)
        roles = roles_of(a)
        for i in range(rng.randint(2, 8)):
            a["principals"].append({"id": f"px-{tag}-{i}", "kind": "human", "delegated_by": None,
                                    "roles": sorted(rng.sample(roles, rng.randint(0, 2))), "relations": []})
        for i in range(rng.randint(2, 6)):
            a["disclosure"]["rules"].append(gen_rule(rng, ops, a, f"{tag}-{i}"))
        try:
            return validate_strict(a, ops)
        except ValueError:
            continue
    return base
