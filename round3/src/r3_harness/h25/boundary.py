"""Oracle-boundary probes (A5b): (i) merit invariance - replace every `merit` string by another and require identical
outcomes/marks (merit_digest excepted); (ii) judgment flip - flip one counted judgment where the ORACLE's final outcome
changes and require the variant to follow the oracle (judged normally on the flipped inputs)."""
from __future__ import annotations

import copy
import random

from . import replay as RP
from .gen_case import INF, Case
from .rename import _sort_bodies

ALT = ("approve", "concur", "ALLOW this", "dissent", "overturn", "deny", "uphold", "zz-" , "ok", "REJECT", "yes", "no")
FLIP = {"concur": "dissent", "dissent": "concur", "uphold": "overturn", "overturn": "uphold"}
KEYS = ("kind", "rid", "actor", "token_ok", "action", "op", "args", "obo", "doc", "spec", "to", "crash", "replay", "approved")


def _record(g):
    calls = [{k: c.get(k) for k in KEYS} for c in g.env.calls]
    outs = [{"kind": c["kind"], "status": c["status"], "reason": c["reason"], "body": c.get("body")}
            for c in g.env.calls if c["kind"] != "advance"]
    return calls, outs


def _finals(out, env):
    C = out["final"]
    return {cid: (C.final(cid, INF, env.clock.now())["state"], C.final(cid, INF, env.clock.now())["outcome"])
            for cid in C.s["cases"]}


def _strip_merit(ms):
    return [{k: v for k, v in m.items() if k not in ("merit_digest", "args_digest", "version")} for m in _sort_bodies(ms)]


def merit_probe(variant, seed: int, i: int) -> dict:
    g = Case(variant, seed, i, tag="merit")
    try:
        g.script()
        calls, outs_a = _record(g)
        marks_a = RP.marks(g.env)
    finally:
        g.env.close()
    rng = random.Random(f"h25-merit-alt-{seed}-{i}")

    def tr(c):
        a = c.get("action")
        if isinstance(a, dict) and a.get("kind") == "judge":
            a["merit"] = rng.choice(ALT) + str(rng.randrange(10 ** 6))
        return c
    env, outs_b = RP.replay(variant, g.domain, g.ops, g.inst["auth"], g.inst["doc"], calls, f"merit2-{seed}-{i}", tr)
    try:
        marks_b = RP.marks(env)
    finally:
        env.close()
    diffs = [n for n, (a, b) in enumerate(zip(outs_a, outs_b))
             if (a["status"], a["reason"]) != (b["status"], b["reason"]) or RP.canon(_sort_bodies(a["body"])) != RP.canon(_sort_bodies(b["body"]))]
    if len(outs_a) != len(outs_b) or RP.canon(_strip_merit(marks_a)) != RP.canon(_strip_merit(marks_b)):
        diffs.append(-1)
    judged = sum(1 for c in calls if isinstance(c.get("action"), dict) and c["action"].get("kind") == "judge")
    return {"case": f"{seed}-{i}", "judge_actions": judged, "diffs": diffs[:5], "fabricated": bool(diffs)}


def flip_probe(variant, seed: int, i: int) -> dict:
    g = Case(variant, seed, i, tag="flip")
    try:
        g.script()
        calls, _ = _record(g)
        out_a = g.env.judge()
        fin_a = _finals(out_a, g.env)
        okj = [c for c, rec in zip([x for x in g.env.calls], g.env.calls) if c["kind"] == "constitutional"
               and isinstance(c.get("action"), dict) and c["action"]["kind"] == "judge" and c["status"] == "OK"]
        rng = random.Random(f"h25-flip-{seed}-{i}")
        if not okj:
            return {"case": f"{seed}-{i}", "candidate": False, "changed": False, "classes": []}
        pick = rng.choice(okj)["rid"]
    finally:
        g.env.close()

    def tr(c):
        a = c.get("action")
        if c.get("rid") == pick and isinstance(a, dict) and a.get("kind") == "judge" and a["value"] in FLIP:
            a["value"] = FLIP[a["value"]]
        return c
    env, _ = RP.replay(variant, g.domain, g.ops, g.inst["auth"], g.inst["doc"], calls, f"flip2-{seed}-{i}", tr)
    try:
        out_b = env.judge()
        fin_b = _finals(out_b, env)
        cls = sorted({k for r in out_b["calls"].values() for k in r["classes"]} | set(out_b["case_classes"]))
    finally:
        env.close()
    return {"case": f"{seed}-{i}", "candidate": True, "changed": fin_a != fin_b,
            "classes": [c for c in cls if c not in ("race_refusal_ok",)]}


_ = copy
