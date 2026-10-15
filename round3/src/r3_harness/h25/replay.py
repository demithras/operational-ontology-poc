"""Replay a recorded call list against a fresh deployment (renaming audit, merit-invariance, judgment-flip). Only the
harness-side INPUTS of the original run are replayed; outcomes are canonicalised for comparison (labels, never truth)."""
from __future__ import annotations

import copy
import json

from r3_oracle import logreplay

from .env import G3Env

OUT_KEYS = ("status", "reason", "body")


def replay(variant, domain, ops, auth, gov, calls, tag, transform=None):
    """-> (env, outs). env is NOT closed (caller reads logs/snapshots, then closes). outs: one dict per non-advance call."""
    env = G3Env(variant, domain, ops, auth, gov, tag)
    env.committed = set()
    outs = []
    for c0 in calls:
        c = transform(copy.deepcopy(c0)) if transform else copy.deepcopy(c0)
        k = c["kind"]
        if k == "advance":
            env.advance(max(0, c["to"] - env.clock.now()))
            continue
        if k == "constitutional":
            if c.get("crash"):
                env.arm(c["crash"])
            rec = env.act(c["actor"], c["action"], c["rid"], bad_token=not c.get("token_ok", True), crash=c.get("crash"),
                          replay=c.get("replay", False))
            if c.get("crash"):
                env.crash_restart()
        elif k == "request":
            rec = env.request(c["actor"], c["op"], c["args"], c["rid"], via="direct", obo=c.get("obo"),
                              approved=c.get("approved", False), bad_token=not c.get("token_ok", True))
        elif k == "set_governance":
            rec = env.set_governance(c["doc"])
        elif k == "set_authority":
            rec = env.set_authority(c["spec"])
        else:
            continue
        outs.append({"kind": k, **{x: rec.get(x) for x in OUT_KEYS}})
    return env, outs


def marks(env) -> list:
    rows = env.reader.log(env.start_seq)
    return [r["data"] for r in rows if r["kind"] == "mark" and r["ref"] == "governance"]


def world(env) -> dict:
    s = env.snapshot()
    return {"objects": {k: v["props"] for k, v in s["objects"].items()}, "links": sorted(map(tuple, s["links"]))}


def canon(x) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"), default=str)


_ = logreplay
