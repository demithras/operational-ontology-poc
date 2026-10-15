"""Mutation proof: for each KNOWN["H23"] mutant, run a fixed seeded sub-corpus against a variant CONSTRUCTED with the
mutant (`factory([m])`, protocol P1b; no global switch) and compare the classification counts with the same
sub-corpus on `factory(())`. Killed iff the mutated run shows MORE of at least one class the mutant should cause.
A mutant whose site is never consulted shows no gain and is reported SURVIVED, never skipped.
`factory(mutants) -> Variant` is built by the caller (registry.load_variant for real variants).
"""
from __future__ import annotations

from r3_shared import mutants

from . import concurrency, surface
from .corpus import DOMAINS, attack_sequence, new_env, run_steps

# world_lock_timeout counts as a detection for every mutant: the mutant made the system observably fail (P11)
EXPECT = {"ledger_after_commit_volatile": ("crash_duplicate_effect", "world_lock_timeout"),
          "unsynchronized_commit": ("concurrency_unserializable", "world_lock_timeout"),
          "identity_substitution": ("forbidden_effect", "identity_expansion", "world_lock_timeout"),
          "mutable_gated_input": ("forbidden_effect", "world_lock_timeout"),
          "backstop_bypass": ("backstop_failure", "world_lock_timeout"),
          "tool_overexposure": ("surface_overexposure", "world_lock_timeout")}
RULES = {"ledger_after_commit_volatile": ["crash_after", "crash_before", "crash_idle", "legit"],
         "unsynchronized_commit": [],
         "identity_substitution": ["ident", "legit", "retarget"], "mutable_gated_input": ["toctou", "legit", "replay"],
         "backstop_bypass": ["hidden", "retarget", "obo", "legit"], "tool_overexposure": ["legit", "hidden"]}


CONC_N = 300  # fixed seeded concurrency sub-corpus for the unsynchronized_commit mutant (dev run 5: 48 gave 1 kill)


def _counts(variant, specs, mutant: str, n: int, seed: int) -> tuple[dict, dict | None]:
    cnt = {c: 0 for c in ("forbidden_effect", "identity_expansion", "backstop_failure", "surface_overexposure",
                          "crash_duplicate_effect", "concurrency_unserializable", "world_lock_timeout")}
    first = None
    if mutant == "unsynchronized_commit":  # concurrency sub-corpus (threads), not the sequential state machine
        for rec in concurrency.run(variant, specs, CONC_N, seed):
            for k in ("concurrency_unserializable", "world_lock_timeout"):
                cnt[k] += k in rec["classes"]
            if "concurrency_unserializable" in rec["classes"] or "world_lock_timeout" in rec["classes"]:
                first = first or {"scenario": rec, "domain": rec["domain"], "attacker": "-", "steps": []}
        return cnt, first
    for i in range(0 if RULES[mutant] == [] else n):
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
                 "mutated_counts": mut, "gain": gain, "sequences": n, "seed": seed,
                 "scenarios": CONC_N if m == "unsynchronized_commit" else n,
                 "kills": sum(max(v, 0) for v in gain.values())}
        if killed and first is not None and "scenario" in first:
            entry["first_counterexample"] = first["scenario"]
        elif killed and first is not None and "surface_row" in first:
            entry["first_counterexample"] = first["surface_row"]
        elif killed and first is not None:
            small = shrink(factory, specs, m, first)
            entry["shrunk_counterexample"] = {"domain": first["domain"], "attacker": first["attacker"],
                                              "steps": small, "original_steps": len(first["steps"])}
        out[m] = entry
    return out
