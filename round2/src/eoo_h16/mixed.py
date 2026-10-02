"""Hypothesis-driven generation of >= N unique mixed-domain packages; each is validated, loaded and rename-checked."""
from __future__ import annotations

import time
from collections import Counter

from hypothesis import HealthCheck, Phase, given, seed as hseed, settings, strategies as st

from eoo_exp.util import canon, load_oracle, sha_text
from eoo_h15.isolation import isolated_constants
from eoo_ir import validate

from .gen import KINDS, build_mixed, imports_domain, origin_counts
from .loadcheck import load_case, rename_invariant


def mixes_both(pkg: dict, meta: dict) -> bool:
    oc = origin_counts(pkg)
    if meta["variant"] == "merged_local":
        return oc["manufacturing"] > 0 and oc["project"] > 0
    own = oc["project"] if meta["variant"] == "import_project" else oc["manufacturing"]
    return own > 0 and imports_domain(pkg)


ORACLE = load_oracle("h16", "kernel_oracle")


def _case(pkg: dict, meta: dict, check_rename: bool) -> dict:
    errs = validate(pkg)
    ld = load_case(pkg) if not errs else {"loaded": False, "error": "not valid"}
    row = {"sha": sha_text(canon(pkg))[:16], "variant": meta["variant"], "valid": not errs, "oracle_legal": ORACLE.legal(pkg), "loaded": ld["loaded"],
           "sizes_match": ld.get("sizes_match"), "unbound": ld.get("unbound"), "origin": origin_counts(pkg),
           "mixes_both": mixes_both(pkg, meta), "cross_added": meta["cross_added"], "n_resources": sum(len(pkg[k]) for k in KINDS)}
    if check_rename and ld["loaded"]:
        row["rename_invariant"] = rename_invariant(pkg)["invariant"]
    if errs:
        row["validation_errors"] = [str(e) for e in errs[:3]]
    if not ld["loaded"]:
        row["error"] = ld.get("error")
    return row


def generate(seed0: int, n_unique: int, max_attempt_factor: int = 3) -> dict:
    seen: dict = {}
    rows, failures, dupes, attempts = [], [], 0, 0
    t0, batch = time.time(), 0
    while len(rows) < n_unique and attempts < n_unique * max_attempt_factor:
        want = max(50, int((n_unique - len(rows)) * 1.1))

        def sink(rnd):
            nonlocal dupes, attempts
            attempts += 1
            try:
                pkg, meta = build_mixed(rnd)
                h = sha_text(canon(pkg))
                if h in seen:
                    dupes += 1
                    return
                seen[h] = True
                row = _case(pkg, meta, check_rename=(len(rows) % 4 == 0))
                rows.append(row)
                if not (row["valid"] and row["oracle_legal"] and row["loaded"] and row["sizes_match"] and row["mixes_both"]
                        and row.get("rename_invariant", True)):
                    failures.append({**row, "package": pkg if len(failures) < 10 else None})
            except Exception as e:  # noqa: BLE001 - recorded, generation continues
                failures.append({"harness_error": f"{type(e).__name__}: {str(e)[:200]}"})

        @hseed(seed0 + batch)
        @settings(max_examples=want, database=None, deadline=None, phases=[Phase.generate],
                  suppress_health_check=list(HealthCheck))
        @given(st.randoms(use_true_random=False))
        def body(rnd):
            sink(rnd)
        with isolated_constants():
            body()
        batch += 1
    by_variant = Counter(r["variant"] for r in rows)
    ok = [r for r in rows if r["valid"] and r["oracle_legal"] and r["loaded"] and r["sizes_match"] and r["mixes_both"]]
    return {"requested_unique": n_unique, "unique_cases": len(rows), "duplicates_skipped": dupes, "attempts": attempts,
            "batches": batch, "seed": seed0, "seconds": round(time.time() - t0, 1), "by_variant": dict(by_variant),
            "valid": sum(r["valid"] for r in rows), "loaded": sum(r["loaded"] for r in rows),
            "sizes_match": sum(bool(r["sizes_match"]) for r in rows), "mixes_both": sum(r["mixes_both"] for r in rows),
            "valid_loaded_mixed": len(ok), "failures": failures,
            "rename_checked": sum("rename_invariant" in r for r in rows),
            "rename_invariant": sum(bool(r.get("rename_invariant")) for r in rows),
            "cross_link_cases": sum(bool(r["cross_added"].get("link_types")) for r in rows),
            "cross_action_cases": sum(bool(r["cross_added"].get("actions")) for r in rows),
            "import_cases": sum(r["variant"] != "merged_local" for r in rows),
            "corpus_hash": sha_text(canon(sorted(r["sha"] for r in rows))), "cases": rows}
