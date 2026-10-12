"""Mutation proof (PROT-H29 s10, ORACLE-AND-HARNESS-G5 s13): every KNOWN["H29"] mutant is built into the variant, run on its own subset of the
SAME seeded corpus (private service sets, same runner / judge code), and must be killed by its OWN class while the clean build shows
NONE of that class on the same sequences (kill rule G3/G4). Subsets are stratified by envelope class (idx % 8 == class - 1)."""
from __future__ import annotations

from pathlib import Path

from r3_shared import mutants as M

from . import aggregate, finalize, runner
from .svcset import SvcSet

RES = {"fail_open_on_authority_outage": (1, 5), "global_halt_on_fault": (2, 4), "stale_cache_after_restart": (5, 0),
       "nondeterministic_recovery": (0, 7), "dependency_failure_as_denial": (1,), "outbox_dropped_on_restart": (0, 2),
       "anchor_skipped_when_unavailable": (4,)}
OWN = {"fail_open_on_authority_outage": ("stale_authority_commit", "forbidden_effect"), "global_halt_on_fault": ("progress",),
       "stale_cache_after_restart": ("stale_authority_after_restart", "stale_authority_commit"),
       "nondeterministic_recovery": ("recovery_nondeterministic", "recovery_divergence"),
       "dependency_failure_as_denial": ("misclassified_dependency_failure",),
       "outbox_dropped_on_restart": ("recovery_divergence", "misclassified_dependency_failure"),
       "anchor_skipped_when_unavailable": ("unanchored_ack",)}
assert set(RES) == set(OWN) == set(M.KNOWN["H29"])


def subset(mutant: str, n_env: int) -> list:
    return [("env", i) for i in range(n_env) if i % 8 in RES[mutant]]


def own_hits(rows: list, agg: dict, mutant: str) -> list:
    """Sequence ids (or progress cells) in which the mutant's OWN class fires."""
    own = OWN[mutant]
    ids = sorted({r["seq"] for r in rows for c in own if c != "progress" and r["classes"].get(c)})
    if "progress" in own:
        p = agg["progress"]
        cells = {"overall": p["overall"], "post_recovery": p["post_recovery"], **{f"class:{c}": v for c, v in p["per_class"].items()},
                 **{f"node:{n}": v for n, v in p["per_node"].items()}}
        ids += [f"ratio<0.95:{k}" for k, v in sorted(cells.items()) if v[0] and v[1] / v[0] < 0.95]
    return ids


def prove(variant: str, vname: str, seed: int, n_env: int, workers: int, workdir: Path, extra_paths=(), clean_rows: list | None = None,
          only: tuple | None = None) -> dict:
    """-> mutation-results.json content. clean_rows: judged rows of the clean main run (control on the same sequence ids)."""
    out = {}
    clean_by_id = {r["seq"]: r for r in (clean_rows or [])}
    for m in (only or M.KNOWN["H29"]):
        jl = subset(m, n_env)
        sv = SvcSet(max(1, workers), Path(workdir) / f"svc-{m}")
        try:
            pre = runner.run_variant(str(sv.root), variant, vname, Path(workdir) / f"run-{m}", f"mut-{m}-dev", seed, 0, 0, 0, workers,
                                     mutants=(m,), extra_paths=extra_paths, job_list=jl, in_process=workers == 0)
            closes = sv.close()
            J = finalize.judge_all(Path(workdir) / f"run-{m}", sv.root, max(1, workers), pre, closes)
        finally:
            sv.cleanup()
        agg = aggregate.aggregate(J["rows"])
        own_ids = own_hits(J["rows"], agg, m)
        ids = [f"env-{i:06d}" for _, i in jl]
        clean = [r for i in ids if (r := clean_by_id.get(i)) is not None]
        clean_agg = aggregate.aggregate(clean) if clean else None
        clean_ids = own_hits(clean, clean_agg, m) if clean_agg else []
        out[m] = {"subset": {"n": len(jl), "residues": list(RES[m]), "ids": ids}, "own_classes": list(OWN[m]), "own_class_count": len(own_ids),
                  "own_ids": own_ids[:200], "clean_count": len(clean_ids) if clean else 0, "clean_ids": clean_ids[:50], "clean_rows_available": len(clean),
                  "harness": agg["harness"], "killed": bool(own_ids) and not clean_ids}
    return out
