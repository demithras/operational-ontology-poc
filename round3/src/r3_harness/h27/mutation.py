"""Mutation proof (PROT-H27 s7): each KNOWN["H27"] mutant is run through a fixed seeded sub-corpus; killed iff at least one
tamper case is ACCEPTED (tamper_accepted / rebinding_accepted / fallback_to_current / continuation_effect /
unanchored_ack) - "killed by the corpus, not by a unit test". A mutant whose switch is never consulted SURVIVES."""
from __future__ import annotations

import random
import shutil
import tempfile

from r3_shared import mutants

from . import corpus

ACCEPT = ("tamper_accepted", "rebinding_accepted", "fallback_to_current", "continuation_effect", "unanchored_ack")
SUB_BASES, SUB_CASES = 3, 90   # per domain bases / cases per mutant (fixed; recorded in mutation-results.json)


def prove(factory, anchor, seed: int, per_domain: int = SUB_BASES, cases: int = SUB_CASES, decisions=(8, 14)) -> dict:
    out = {}
    for name in mutants.KNOWN["H27"]:
        work = tempfile.mkdtemp(prefix=f"h27-mut-{name}-")
        try:
            variant = factory((name,))
            bases = corpus.build_bases(variant, anchor, work, seed + 17, per_domain, decisions, tag="m")
            pl = corpus.plan(random.Random(seed + 29), cases, len(bases))
            hit, first, ran = {}, None, 0
            for rec in corpus.run_plan(variant, anchor, bases, pl, work, seed + 31, tag="mc"):
                ran += 1
                for c in rec["classes_hit"]:
                    if c in ACCEPT:
                        hit[c] = hit.get(c, 0) + 1
                        first = first or {"case": rec["case"], "classes": rec["classes"], "applied": rec["applied"],
                                          "flags": rec["flags"], "class": c, "primitives": rec["primitives"]}
            for b in bases:
                if b.unanchored:
                    hit["unanchored_ack"] = hit.get("unanchored_ack", 0) + len(b.unanchored)
            out[name] = {"killed": bool(hit), "killing_classes": hit, "first_killing_case": first, "cases_run": ran,
                         "bases": len(bases), "divergent_clean_decisions": sum(len(b.divergences) for b in bases)}
        finally:
            shutil.rmtree(work, ignore_errors=True)
    return out
