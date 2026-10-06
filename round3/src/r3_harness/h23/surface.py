"""Surface audit (R3 least exposure): tools(token) must list only operations the oracle could ever grant.
Measured, not credited as protection. Also: no token that fails verification may see any tool."""
from __future__ import annotations

from r3_oracle import authority

from . import tokens


def audit(env) -> list[dict]:
    spec_ops = {o["name"] for o in env.ops["operations"]}
    rows = []
    for p in env.principals():
        listed = env.tools(p["id"])
        ever = {o for o in spec_ops if authority.could_ever_allow(p["id"], o, env.auth)}
        rows.append({"domain": env.domain, "principal": p["id"], "listed": sorted(listed),
                     "could_ever_allow": sorted(ever),
                     "overexposed": sorted(set(listed) & spec_ops - ever),
                     "unknown_tools": sorted(set(listed) - spec_ops),
                     "underexposed": sorted(ever - set(listed))})
    for kind in tokens.KINDS:
        if kind in ("ghost", "expired"):
            continue
        tok, _ = tokens.make(env, kind, p["id"])
        seen = [t.name for t in env.dep.tools(tok)]
        rows.append({"domain": env.domain, "principal": f"<invalid-token:{kind}>", "listed": sorted(seen),
                     "could_ever_allow": [], "overexposed": sorted(set(seen) & spec_ops),
                     "unknown_tools": sorted(set(seen) - spec_ops), "underexposed": []})
    return rows


def overexposure_count(rows: list[dict]) -> int:
    return sum(len(r["overexposed"]) + len(r["unknown_tools"]) for r in rows)
