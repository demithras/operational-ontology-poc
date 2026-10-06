"""Mutation proof: for each KNOWN["H23"] mutant, run a fixed seeded sub-corpus against a variant CONSTRUCTED with the
mutant (`factory([m])`, protocol P1b; no global switch) and compare the classification counts with the same
sub-corpus on `factory(())`. Killed iff the mutated run shows MORE of at least one class the mutant should cause.
A mutant whose site is never consulted shows no gain and is reported SURVIVED, never skipped.
`factory(mutants) -> Variant` is built by the caller (registry.load_variant for real variants).
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


def _fails(factory, specs, mutant: str, domain: str, attacker: str, steps: list) -> bool:
    env = new_env(factory([mutant]), domain, specs, "shrink")
    try:
        calls = run_steps(env, steps)
    finally:
        env.close()
    return any(k in EXPECT[mutant] for c in calls for k in c["classes"])


def shrink(factory, specs, mutant: str, rec: dict) -> list[dict]:
    """Greedy delta-debugging over the recorded concrete steps."""
    steps = list(rec["steps"])
    changed = True
    while changed and len(steps) > 1:
        changed = False
        for i in range(len(steps)):
            cand = steps[:i] + steps[i + 1:]
            if cand and _fails(factory, specs, mutant, rec["domain"], rec["attacker"], cand):
                steps, changed = cand, True
                break
    return steps


def prove(factory, specs, n: int = 150, seed: int = 4242) -> dict:
    out = {}
    for m in mutants.KNOWN["H23"]:
        base, _ = _counts(factory(()), specs, m, n, seed)
        mut, first = _counts(factory([m]), specs, m, n, seed)
        gain = {k: mut[k] - base[k] for k in EXPECT[m]}
        killed = any(v > 0 for v in gain.values())
        entry = {"killed": killed, "expected_classes": list(EXPECT[m]), "baseline_counts": base,
                 "mutated_counts": mut, "gain": gain, "sequences": n, "seed": seed}
        if killed and first is not None and "surface_row" in first:
            entry["first_counterexample"] = first["surface_row"]
        elif killed and first is not None:
            small = shrink(factory, specs, m, first)
            entry["shrunk_counterexample"] = {"domain": first["domain"], "attacker": first["attacker"],
                                              "steps": small, "original_steps": len(first["steps"])}
        out[m] = entry
    return out
