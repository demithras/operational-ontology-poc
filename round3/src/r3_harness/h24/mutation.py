"""Mutation proof (A4 mutation-results.json): for each KNOWN["H24"] name run a fixed seeded sub-corpus against a variant
CONSTRUCTED with the mutant (`factory([m])`, no global switch) and the same sub-corpus on `factory(())` as control.
Killed iff the mutated run shows MORE rows of at least one class the mutant should cause than the control. A mutant whose
site is never consulted shows no gain and is reported SURVIVED, never skipped."""
from __future__ import annotations

from r3_shared import mutants

from .gen_race import run_race
from .gen_seq import run_sequence

# world_lock_timeout counts as a detection for every mutant: the mutant made the system observably fail
EXPECT = {"non_attenuating_delegation": ("scope_amplification", "forbidden_effect", "world_lock_timeout"),
          "stale_authority_cache": ("post_boundary_effect", "world_lock_timeout"),
          "revoke_commit_reorder": ("linearizability_violation", "authority_ack_without_commit", "post_boundary_effect",
                                    "world_lock_timeout"),
          "expiry_inclusive": ("post_boundary_effect", "world_lock_timeout")}
RACE_TYPES = {"non_attenuating_delegation": ("RV", "SEQ"), "stale_authority_cache": ("RV", "RA", "SEQ"),
              "revoke_commit_reorder": ("SEQ", "RV", "RA"), "expiry_inclusive": ("EX", "SEQ")}
SEED_SALT = 7_000_003


def _run(variant, specs, name: str, n_seq: int, n_race: int, seed: int):
    cnt = {c: 0 for c in EXPECT[name]}
    first = None
    cases = [("seq", i) for i in range(n_seq)] + [("race", j) for j in range(n_race)]
    for kind, i in cases:
        try:
            rec = run_sequence(variant, specs, seed, i) if kind == "seq" else \
                run_race(variant, specs, seed, i, RACE_TYPES[name][i % len(RACE_TYPES[name])])
        except Exception as exc:  # noqa: BLE001 - a mutant that breaks the harness path is data
            cnt["world_lock_timeout"] += 1
            first = first or {"case": f"{kind}-{i}", "error": repr(exc)}
            continue
        hit = [c for r in rec["calls"] for c in r["classes"] if c in cnt] + [c for c in rec["case_classes"] if c in cnt]
        for c in hit:
            cnt[c] += 1
        if hit and first is None:
            first = {"case": rec["id"], "class": hit[0], "calls": [
                {k: r.get(k) for k in ("kind", "actor", "obo", "op", "edge_id", "status", "classes", "seq", "tick")}
                for r in rec["calls"] if set(r["classes"]) & set(EXPECT[name])][:4]}
    return cnt, first


def prove(factory, specs, n_seq: int = 60, n_race: int = 60, seed: int = 1) -> dict:
    out = {}
    for name in mutants.KNOWN["H24"]:
        s = seed + SEED_SALT
        control, _ = _run(factory(()), specs, name, n_seq, n_race, s)
        mutated, first = _run(factory([name]), specs, name, n_seq, n_race, s)
        gain = {c: mutated[c] - control[c] for c in mutated if mutated[c] > control[c]}
        out[name] = {"killed": bool(gain), "killing_class": next(iter(gain), None), "control": control,
                     "mutated": mutated, "first_killing_case": first if gain else None,
                     "sub_corpus": {"sequences": n_seq, "races": n_race, "seed": s}}
    return out
