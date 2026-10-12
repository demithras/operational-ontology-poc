"""H29 sequence generator (ORACLE-AND-HARNESS-G5 s2): strata, class plan, reachability and envelope validity built in. A sequence is a
JSON-able dict; the official corpus is a counted, seeded list drawn from the SAME frozen rule table the state machine uses. Never raises:
an exhausted draw is returned as None and counted (generator_redraw_exhausted)."""
from __future__ import annotations

import random

from r3_harness.h23.chooser import RandChooser
from r3_harness.h28.adapters import PRIMS

from . import faults, gen_draw, gen_emit as E, gen_eps as G, rules, specs
from .gen_model import Plan

DOMAINS = specs.DOMAINS
SECOND = {"F1": ("F2", "F4", "F5"), "F2": ("F3", "F4"), "F3": ("F4", "F5"), "F4": ("F5", "F7"), "F5": ("F3", "F4"),
          "F6": ("F4",), "F7": ("F3", "F5"), "F8": ("F4",)}
MAIN_PRIMS = tuple(p for p in PRIMS if p != "H0")
MIN_STEPS, MAX_STEPS, MAX_TRIES = 24, 48, 40


def _episode(plan, ch, cls: str, i: int, hdr: dict) -> None:
    v = i // 8
    if cls == "F1":
        cp = faults.CRASH_POINTS[v % len(faults.CRASH_POINTS)]
        hdr["cp"].append(cp)
        G.f1_crash(plan, ch, cp, v)
    elif cls == "F2":
        G.f2_auth(plan, ch, ["drop", "reply_lost"][v % 2], v // 2)
    elif cls == "F3":
        byz = v % 3 == 2
        if byz:
            hdr["byz"] = {"prims": sorted(set(ch.choice(MAIN_PRIMS) for _ in range(ch.randint(1, 2)))), "k": ch.randint(1, 6)}
        G.f3_ext(plan, ch, byz, v)
    elif cls == "F4":
        if v % 3 == 2:
            hdr["obs_lag"] = ch.randint(1, faults.LAG_MAX)
        G.f4_events(plan, ch, v)
    elif cls == "F5":
        G.f5_partition(plan, ch, v)
    elif cls == "F6":
        G.f6_stale(plan, ch, v)
    elif cls == "F7":
        G.f7_attacker(plan, ch, v)
    elif cls == "F8":
        G.f8_tamper(plan, ch, v)


def _closing(plan, ch) -> None:
    E.close_windows(plan)
    E.dispatch(plan)
    if plan.intents:
        last = max(t for t, _ in plan.intents.values())
        need = last + 8 + 2 - plan.t
        plan.advance(max(1, need))
        E.dispatch(plan)
        for rid in sorted(plan.intents):
            E.reconcile(plan, rid)
    if plan.kills:
        plan.add({"op": "recovery_schedule"})


def _finish(plan, hdr: dict) -> dict | None:
    for st in plan.steps:
        rules.validate_step(st)
    n = len(plan.steps)
    if hdr["stratum"] == "env":
        ok, why = faults.envelope_ok({"steps": plan.steps})
        if not ok:
            plan.stats["envelope_redraw"] = why
            return None
    hdr["steps"] = plan.steps
    hdr["class_windows"] = plan.class_windows
    hdr["planned"] = {"requests": sum(1 for s in plan.steps if s["op"] == "request"), "steps": n,
                      "stale_sensitive": plan.stats.get("stale_sensitive", 0), "attacker": plan.stats.get("attacker")}
    hdr["attacker"] = plan.stats.get("attacker")
    return hdr


def build_env(idx: int, seed: int, stats: dict) -> dict | None:
    cls0 = rules.CLASSES[idx % 8]
    for attempt in range(MAX_TRIES):
        ch = RandChooser(random.Random(f"{seed}:env:{idx}:{attempt}"))
        domain = DOMAINS[(idx // 2) % 2]
        plan = Plan(domain)
        hdr = {"id": f"env-{idx:06d}", "stratum": "env", "domain": domain, "seed": seed, "idx": idx, "classes": [cls0], "cp": [],
               "boundary": None, "obs_lag": 0, "byz": None}
        E.fill(plan, ch, 2, tag="warm")
        _episode(plan, ch, cls0, idx, hdr)
        if ch.chance(0.4):
            c2 = ch.choice(SECOND[cls0])
            E.close_windows(plan)
            plan.advance(1)
            hdr["classes"].append(c2)
            _episode(plan, ch, c2, idx + ch.randint(1, 7), hdr)
        E.fill(plan, ch, 1) if len(plan.steps) < MIN_STEPS else None
        _closing(plan, ch)
        while len(plan.steps) < MIN_STEPS:
            E.fill(plan, ch, 1)
        if len(plan.steps) > MAX_STEPS:
            stats["too_long"] = stats.get("too_long", 0) + 1
            continue
        out = _finish(plan, hdr)
        if out is not None:
            stats["attempts"] = stats.get("attempts", 0) + attempt
            return out
    stats["generator_redraw_exhausted"] = stats.get("generator_redraw_exhausted", 0) + 1
    return None


def build_ctrl(idx: int, seed: int, stats: dict) -> dict | None:
    for attempt in range(MAX_TRIES):
        ch = RandChooser(random.Random(f"{seed}:ctrl:{idx}:{attempt}"))
        domain = DOMAINS[idx % 2]
        plan = Plan(domain)
        hdr = {"id": f"ctrl-{idx:06d}", "stratum": "ctrl", "domain": domain, "seed": seed, "idx": idx, "classes": [], "cp": [],
               "boundary": None, "obs_lag": 0, "byz": None}
        E.fill(plan, ch, 3, tag="warm")
        E.approve_flow(plan, ch)
        d = gen_draw.draw(plan, ch, "deny")
        if d is not None:
            plan.advance(1)
            E.request(plan, d, tag="deny")
        E.read(plan, gen_draw.any_read(plan, ch), tag="ctrl")
        s = ch.choice(G._ext_systems(plan))
        p = gen_draw.draw(plan, ch, "ok_ext", system=s)
        if p is not None:
            plan.advance(1)
            E.request(plan, p)
            E.dispatch(plan)
        E.fill(plan, ch, 8)
        _closing(plan, ch)
        while len(plan.steps) < MIN_STEPS:
            E.fill(plan, ch, 1)
        if len(plan.steps) > MAX_STEPS:
            continue
        out = _finish(plan, hdr)
        if out is not None:
            return out
    stats["generator_redraw_exhausted"] = stats.get("generator_redraw_exhausted", 0) + 1
    return None


def build_bnd(idx: int, seed: int, stats: dict) -> dict | None:
    b = ("B1", "B2", "B3", "B4")[idx % 4]
    ch = RandChooser(random.Random(f"{seed}:bnd:{idx}"))
    domain = DOMAINS[(idx // 4) % 2]
    plan = Plan(domain)
    hdr = {"id": f"bnd-{idx:06d}", "stratum": "bnd", "domain": domain, "seed": seed, "idx": idx, "classes": [], "cp": [],
           "boundary": b, "obs_lag": 0, "byz": None}
    E.fill(plan, ch, 3, tag="warm")
    if b == "B1":
        plan.advance(1)
        plan.fault("B1", "AUTH", "drop", 60)
        E.fill(plan, ch, 4, gap=2)
        E.fill(plan, ch, 1, want="deny")
    elif b == "B2":
        plan.advance(1)
        plan.fault("B2", "ANCHOR", "drop", 60)
        E.fill(plan, ch, 4, gap=2)
    elif b == "B3":
        s = ch.choice(G._ext_systems(plan))
        p = gen_draw.draw(plan, ch, "ok_ext", system=s)
        if p is not None:
            plan.advance(1)
            r, _ = E.request(plan, p)
            E.dispatch(plan)
            plan.advance(1)
            plan.fault("B3", "OBS", "drop", 60)
            plan.advance(10)
            E.dispatch(plan)
            E.reconcile(plan, r)
            plan.advance(2)
            E.reconcile(plan, r)
        E.fill(plan, ch, 2)
    else:
        rid = (E.fill(plan, ch, 1) or [None])[0]
        pk = gen_draw.draw(plan, ch, "ok_local") or gen_draw.draw(plan, ch, "ok")
        key = plan.new_rid("c")
        E.crash(plan, "CP6_idle", key)
        plan.advance(1)
        kill_t = plan.t
        if pk is not None:
            E.request(plan, pk, rid=key)
        plan.advance(1)
        plan.add({"op": "tamper", "what": "delete_store"})
        E.resume(plan, kill_t)
        for r in [x for x in (rid, key) if x]:
            plan.add({"op": "redeliver", "rid": r, "copies": 1, "concurrent": False})
        E.fill(plan, ch, 2)
    for st in plan.steps:
        rules.validate_step(st)
    hdr["steps"], hdr["class_windows"], hdr["attacker"] = plan.steps, plan.class_windows, None
    hdr["planned"] = {"requests": sum(1 for s in plan.steps if s["op"] == "request"), "steps": len(plan.steps), "stale_sensitive": 0, "attacker": None}
    return hdr


BUILDERS = {"env": build_env, "ctrl": build_ctrl, "bnd": build_bnd}


def build(stratum: str, idx: int, seed: int, stats: dict) -> dict | None:
    return BUILDERS[stratum](idx, seed, stats)
