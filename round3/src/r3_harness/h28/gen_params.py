"""Case PARAMETERS drawn with Hypothesis strategies (PROT-H28 s8 / Q14; ORACLE-AND-HARNESS-G4 s2): derandomised by the run seed
(`@seed`, database=None, generate phase only) so the corpus is a reproducible, counted list - never adaptively generated. The strata
that carry the frozen floors (per primitive, per (domain, system), crash, none-class, observer fault) are assigned by case index;
Hypothesis draws everything else (companion primitives, delays, schedule shape, faults). Never raises."""
from __future__ import annotations

from hypothesis import HealthCheck, Phase, Verbosity, given, seed as hseed, settings, strategies as st

from r3_harness.h23.chooser import HypChooser, RandChooser

from .adapters import PRIMS
from .specs import GEN_OP

PAIRS = (("manufacturing", "WMS"), ("manufacturing", "ERP"), ("manufacturing", "MES"), ("manufacturing", "GEN-NULL"),
         ("project", "REGISTRY"), ("project", "NOTIFY"), ("project", "GEN-NULL"))
SYSTEM_OP = {"WMS": "transfer_inventory", "ERP": "expedite_purchase_order", "MES": "reschedule_work_order",
             "REGISTRY": "publish_result", "NOTIFY": "notify_reviewer", "GEN-NULL": GEN_OP}
MAIN = tuple(p for p in PRIMS if p != "H0")      # the 13 Byzantine primitives
CRASH_EVERY, FAULT_EVERY = 12, 9                 # 8% crash-after-commit, 11% observer-fault strata (floors 200 / 300 at 5,600)


def params_from(ch, i: int, kind: str) -> dict:
    """One case's parameters from a chooser (Hypothesis `data` or a seeded Random). kind: byz | control. The sequence of draws is
    FIXED (Hypothesis requires draw structure independent of state); the index-dependent strata are applied afterwards."""
    domain, system = PAIRS[i % len(PAIRS)]
    extras = [ch.choice(MAIN) for _ in range(2)]
    n_extra = ch.choice([0, 0, 1, 2])
    k, reps = ch.randint(1, 12), ch.randint(2, 3)
    direct, replay, appr, denied = ch.chance(0.2), ch.chance(0.15), ch.chance(0.1), ch.chance(0.2)
    fkind, fk = ch.choice(["unavailable", "lagging"]), ch.randint(1, 6)
    extra_dispatch, mid = ch.randint(0, 2), ch.randint(0, 2)
    adv = [ch.randint(0, 3) for _ in range(6)]
    p = {"idx": i, "kind": kind, "domain": domain, "system": system, "op": SYSTEM_OP[system], "prims": [], "k": 2, "reps": 2}
    if kind == "byz":
        main = MAIN[(i // len(PAIRS)) % len(MAIN)]
        pick = {main, *extras[:n_extra]}
        p["prims"] = [q for q in PRIMS if q in pick]
        p["main"], p["k"], p["reps"] = main, k, reps
    p["via"] = "direct" if direct else "call_tool"
    p["crash"] = "after_commit" if kind == "byz" and i % CRASH_EVERY == 5 else None
    p["fault"] = {"kind": fkind, "k": fk} if kind == "byz" and i % FAULT_EVERY == 4 else None
    p["replay"] = replay and not p["crash"]
    p["approved_flow"] = kind == "byz" and appr and system != "GEN-NULL"
    p["denied"] = kind == "byz" and denied and system != "GEN-NULL" and not p["crash"]   # governance probe request
    p["extra_dispatch"], p["mid"], p["adv"] = extra_dispatch, mid, adv
    return p


def draw_params(run_seed: int, n: int, kind: str = "byz", start: int = 0) -> tuple[list[dict], dict]:
    """n case parameter dicts for indexes start..start+n-1, drawn by ONE Hypothesis run (re-run with a fresh sub-seed if it
    returns fewer). stats counts Hypothesis runs."""
    out: list[dict] = []
    stats = {"hypothesis_runs": 0, "hypothesis_shortfall": 0}
    sub = 0
    while len(out) < n and sub < 50:
        need = n - len(out)

        @hseed(run_seed * 100_003 + sub)
        @settings(max_examples=need + 1, derandomize=False, database=None, phases=[Phase.generate], deadline=None,
                  suppress_health_check=list(HealthCheck), verbosity=Verbosity.quiet)
        @given(st.data())
        def run(data):
            q = params_from(HypChooser(data), start + len(out), kind)   # always draw: structure must not depend on state
            if len(out) < n:
                out.append(q)

        run()
        stats["hypothesis_runs"] += 1
        if len(out) < n:
            stats["hypothesis_shortfall"] += 1
        sub += 1
    while len(out) < n:                              # last resort (counted): seeded Random draws, never raises
        import random
        out.append(params_from(RandChooser(random.Random(run_seed + len(out))), start + len(out), kind))
        stats["hypothesis_shortfall"] += 1
    return out[:n], stats
