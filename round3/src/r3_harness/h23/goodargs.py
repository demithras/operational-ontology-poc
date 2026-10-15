"""Argument generation for attack rules. Candidates are drawn from the LIVE world, then ranked with the ORACLE
(harness-side use only) so legitimate controls are mostly valid and attacks aim at requests that WOULD commit
for someone. Nothing here depends on a variant."""
from __future__ import annotations

from r3_oracle import ops_model

INT_POOL = {"quantity": [1, 3, 5, 10, 20, 40, 60, 70, 80, 81, 100, 0, -1], "expedite_fee": [0, 10, 100, 500, 501, 900],
            "new_planned_start": [1, 5, 20, 50]}
STR_POOL = {"claim": ["claim alpha", "claim beta", "gamma", "delta claim", "ephemeral:x", " "],
            "freeze_hash": ["abc123", "f" * 64, ""]}
JSON_POOL = [{"min": 1}, {"min": 10}, {"max": 5}, 7]


def _value(inp: dict, snap: dict, ch):
    t, n = inp["type"], inp["name"]
    if t == "resource":
        keys = [k.split(":", 1)[1] for k in snap["objects"] if k.startswith(inp["resource_type"] + ":")]
        return ch.choice(keys + ["NOPE"] if ch.chance(0.05) or not keys else keys)
    if t == "integer":
        return ch.choice(INT_POOL.get(n, [0, 1, 5, 100]))
    if t == "json":
        return ch.choice(JSON_POOL)
    return ch.choice(STR_POOL.get(n, ["x", "y", ""]))


def random_args(op: dict, snap: dict, ch) -> dict:
    return {i["name"]: _value(i, snap, ch) for i in op["inputs"] if i["required"] or ch.chance(0.5)}


def pick_args(env, op: dict, ch, subject: str, want: str = "commit", on_behalf_of=None, tries: int = 10) -> dict:
    """want: 'commit' prefers args the oracle would commit for `subject`; 'any' takes the first draw."""
    snap = env.snapshot()
    first = None
    for _ in range(tries):
        a = random_args(op, snap, ch)
        first = first or a
        if want == "any":
            return a
        o = ops_model.evaluate(env.ops, env.auth, subject, on_behalf_of, op["name"], a, snap, env.clock.now(),
                               frozenset(env.committed), None)
        if o.commits:
            return a
    return first
