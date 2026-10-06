"""Mutation proof: for each KNOWN["H23"] mutant, run a fixed seeded sub-corpus with the switch ON and compare the
classification counts with the same sub-corpus switch OFF. Killed iff the mutated run shows MORE of at least one
class the mutant should cause. A switch that is never consulted is reported SURVIVED (consulted=false), not skipped.
"""
from __future__ import annotations

from r3_shared import mutants

from . import surface
from .corpus import DOMAINS, attack_sequence, new_env, run_steps

EXPECT = {"identity_substitution": ("forbidden_effect", "identity_expansion"),
          "mutable_gated_input": ("forbidden_effect",),
          "backstop_bypass": ("backstop_failure",),
          "tool_overexposure": ("surface_overexposure",)}
RULES = {"identity_substitution": ["ident", "legit", "retarget"], "mutable_gated_input": ["toctou", "legit", "replay"],
         "backstop_bypass": ["hidden", "retarget", "obo", "legit"], "tool_overexposure": ["legit", "hidden"]}


def _counts(variant, specs, mutant: str, n: int, seed: int) -> tuple[dict, dict | None]:
    cnt = {c: 0 for c in ("forbidden_effect", "identity_expansion", "backstop_failure", "surface_overexposure")}
    first = None
    for i in range(n):
        rec = attack_sequence(variant, specs, seed, i, RULES[mutant])
        for c in rec["calls"]:
            for k in c["classes"]:
                if k in cnt:
                    cnt[k] += 1
            if first is None and any(k in EXPECT[mutant] for k in c["classes"]):
                first = rec
    for d in DOMAINS:
        env = new_env(variant, d, specs, f"surf-{mutant}-{d}")
        try:
            rows = surface.audit(env)
            cnt["surface_overexposure"] += surface.overexposure_count(rows)
            if first is None and mutant == "tool_overexposure":
                first = next(({"surface_row": r, "domain": d, "attacker": r["principal"], "steps": []}
                              for r in rows if r["overexposed"] or r["unknown_tools"]), None)
        finally:
            env.close()
    return cnt, first


def _fails(variant, specs, mutant: str, domain: str, attacker: str, steps: list) -> bool:
    env = new_env(variant, domain, specs, "shrink")
    try:
        with mutants.enabled(mutant):
            calls = run_steps(env, steps)
    finally:
        env.close()
    return any(k in EXPECT[mutant] for c in calls for k in c["classes"])


def shrink(variant, specs, mutant: str, rec: dict) -> list[dict]:
    """Greedy delta-debugging over the recorded concrete steps."""
    steps = list(rec["steps"])
    changed = True
    while changed and len(steps) > 1:
        changed = False
        for i in range(len(steps)):
            cand = steps[:i] + steps[i + 1:]
            if cand and _fails(variant, specs, mutant, rec["domain"], rec["attacker"], cand):
                steps, changed = cand, True
                break
    return steps


def prove(variant, specs, n: int = 150, seed: int = 4242) -> dict:
    out = {}
    for m in mutants.KNOWN["H23"]:
        mutants.reset()
        base, _ = _counts(variant, specs, m, n, seed)
        mutants.reset()
        with mutants.enabled(m):
            mut, first = _counts(variant, specs, m, n, seed)
            consulted = m in mutants.CONSULTED
        gain = {k: mut[k] - base[k] for k in EXPECT[m]}
        killed = any(v > 0 for v in gain.values())
        entry = {"killed": killed, "consulted": consulted, "expected_classes": list(EXPECT[m]),
                 "baseline_counts": base, "mutated_counts": mut, "gain": gain, "sequences": n, "seed": seed}
        if killed and first is not None and "surface_row" in first:
            entry["first_counterexample"] = first["surface_row"]
        elif killed and first is not None:
            small = shrink(variant, specs, m, first)
            entry["shrunk_counterexample"] = {"domain": first["domain"], "attacker": first["attacker"],
                                              "steps": small, "original_steps": len(first["steps"])}
        out[m] = entry
    mutants.reset()
    return out
