"""Mutation proof (A4 mutation-results.json): for each KNOWN["H25"] name run a fixed seeded sub-corpus against a variant
CONSTRUCTED with the mutant (`factory([m])`, no global switch) and the same sub-corpus on `factory(())` as control. The
first four are killed iff the mutated run shows MORE rows of a class the mutant should cause than the control (a
sub-corpus a mutant never touches shows no gain and is reported SURVIVED, never skipped). domain_privilege_branch is
killed by the domain-branch AUDIT (metamorphic renaming on the mutant build, or the static scan of the variant source)."""
from __future__ import annotations

from r3_shared import mutants

from . import audit
from .gen_case import run_case
from .gen_race import run_race

# world_lock_timeout counts as a detection for every mutant: the mutant made the system observably fail
EXPECT = {"precedence_inverted": ("procedural_mismatch", "illegitimate_effect", "progress_loss", "world_lock_timeout"),
          "quorum_weakened": ("procedural_mismatch", "illegitimate_effect", "fabricated_judgment", "world_lock_timeout"),
          "emergency_no_expiry": ("emergency_violation", "procedural_mismatch", "illegitimate_effect", "world_lock_timeout"),
          "merit_autofill": ("fabricated_judgment", "world_lock_timeout")}
RACE_TYPES = {"precedence_inverted": ("EA", "ES"), "quorum_weakened": ("JJ", "EA"), "emergency_no_expiry": ("AX", "AX_EDGE", "AE"),
              "merit_autofill": ("EA", "ES")}
SEED_SALT = 7_000_003


def _run(variant, name: str, n_cases: int, n_races: int, seed: int):
    cnt = {c: 0 for c in EXPECT[name]}
    first = None
    jobs = [("case", i) for i in range(n_cases)] + [("race", j) for j in range(n_races)]
    for kind, i in jobs:
        try:
            rec = run_case(variant, seed, i) if kind == "case" else \
                run_race(variant, seed, i, RACE_TYPES[name][i % len(RACE_TYPES[name])])
        except Exception as exc:  # noqa: BLE001 - a mutant that breaks the harness path is data
            cnt["world_lock_timeout"] += 1
            first = first or {"case": f"{kind}-{i}", "error": repr(exc)}
            continue
        hit = [c for r in rec["calls"] for c in r["classes"] if c in cnt] + [c for c in rec["case_classes"] if c in cnt]
        for c in hit:
            cnt[c] += 1
        if hit and first is None:
            first = {"case": rec["id"], "class": hit[0], "calls": [
                {k: r.get(k) for k in ("kind", "action", "actor", "status", "reason", "classes", "seq", "tick")}
                for r in rec["calls"] if set(r["classes"]) & set(EXPECT[name])][:4]}
    return cnt, first


def prove(factory, seed: int = 1, n_cases: int = 120, n_races: int = 40, n_audit: int = 60, scan_pkg=None,
          keep_roles=(), scan_sources=None) -> dict:
    out = {}
    for name in mutants.KNOWN["H25"]:
        s = seed + SEED_SALT
        if name == "domain_privilege_branch":
            ctl = audit.rename_audit(factory(()), s, n_audit, domain="project", keep_roles=keep_roles)
            mut = audit.rename_audit(factory([name]), s, n_audit, domain="project", keep_roles=keep_roles)
            scan = audit.static_scan(pkg_dir=scan_pkg, sources=scan_sources) if (scan_pkg or scan_sources) else {"hit_count": 0, "hits": []}
            killed = mut["domain_branch"] > ctl["domain_branch"] or scan["hit_count"] > 0
            out[name] = {"killed": bool(killed), "killing_class": "domain_branch" if killed else None,
                         "killed_by": "audit", "control": {"domain_branch": ctl["domain_branch"]},
                         "mutated": {"domain_branch": mut["domain_branch"], "static_hits": scan["hit_count"]},
                         "first_killing_case": mut["first"] or (scan["hits"][:1] or None),
                         "sub_corpus": {"audit_cases": n_audit, "domain": "project", "seed": s}}
            continue
        control, _ = _run(factory(()), name, n_cases, n_races, s)
        mutated, first = _run(factory([name]), name, n_cases, n_races, s)
        gain = {c: mutated[c] - control[c] for c in mutated if mutated[c] > control[c]}
        out[name] = {"killed": bool(gain), "killing_class": next(iter(gain), None), "killed_by": "corpus", "control": control,
                     "mutated": mutated, "first_killing_case": first if gain else None,
                     "sub_corpus": {"cases": n_cases, "races": n_races, "seed": s}}
    return out
