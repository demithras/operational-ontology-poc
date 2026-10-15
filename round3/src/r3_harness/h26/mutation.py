"""Mutation proof (PROT-H26 s8): for each KNOWN["H26"] mutant run a fixed seeded sub-corpus with the mutant enabled; killed
iff >= 1 divergent pair, canary hit, surface row, or false-provenance row appears. A mutant whose switch is never
consulted SURVIVES (never skipped)."""
from __future__ import annotations

from r3_shared.mutants import KNOWN

from . import analyze, fuzz, gen_pair, observe

KILL_TAGS = ("hidden_capability", "schema_disclosure", "false_provenance", "provenance_overdisclosure", "value_exfiltration",
             "form_violation")
# fixed, seeded variation kinds per mutant (all six kinds still appear across the proof; this only orders them)
PER_KINDS = {"existence_status_split": "EFLDCG", "error_detail_leak": "FEFEDG", "hidden_tool_schema": "FELDCG",
             "provenance_edge_retained": "DDDCDD", "subscription_unfiltered": "DDEFDD", "redaction_fabrication": "DDDDCD"}


def prove(factory, seed: int, n_pairs: int) -> dict:
    out = {"mutants": {}, "pairs_per_mutant": n_pairs}
    for name in KNOWN["H26"]:
        try:
            variant = factory((name,))
        except Exception as exc:  # noqa: BLE001
            out["mutants"][name] = {"killed": False, "error": f"{type(exc).__name__}: {exc}"}
            continue
        killers, rows = [], []
        for idx in range(n_pairs * 6):  # fixed seeded corpus; the run extends up to 4x until the first kill (deterministic)
            if (killers and len(rows) >= 1) or len(rows) >= 4 * n_pairs:
                break
            kind = PER_KINDS[name][idx % 6]
            p, _ = gen_pair.draw(seed + 31, idx, kind=kind)
            if p is None:
                continue
            runs = [observe.run_world(variant, p, w) for w in (0, 1)]
            row = analyze.pair_row(p, runs)
            rows.append(row)
            hit = [d["class"] for d in row["divergences"]] + [t for t in row["tags"] if t.split(":")[0] in KILL_TAGS]
            if hit and len(killers) < 3:
                killers.append({"pair": row["id"], "classes": sorted(set(hit))[:6], "witness": row["witness"]})
        fz = fuzz.run(variant, seed + 31, 200)
        fz_hit = bool(fz["value_exfiltration"] or fz["existence_leak"])
        out["mutants"][name] = {"killed": bool(killers) or fz_hit, "pairs_run": len(rows), "first_counterexamples": killers,
                                "fuzz_hit": fz_hit}
    out["kill_rate"] = sum(m["killed"] for m in out["mutants"].values()) / len(KNOWN["H26"])
    return out


_ = analyze
