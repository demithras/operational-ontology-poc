"""Mutation proof (P1f-9; PROT-H28 s9): every KNOWN["H28"] build runs a frozen stratified corpus subset against its own private
ExternalWorld; the clean build runs the same subset. Killed = own class > 0 AND the non-mutated build is 0 on that class
(exact case ids reported - G3 lesson: N must equal the inheriting population)."""
from __future__ import annotations

import json
import multiprocessing
import os
import tempfile
from pathlib import Path

from r3_shared import mutants

from . import finalize, specs, worlds
from .caserun import RunCtx, run_case
from .gen_case import build_case
from .gen_params import PAIRS, draw_params
from .runner import RAW, seed_external

OWN_CLASS = {"adapter_success_trusted": "false_reconciled_success", "credential_scope_broadened": "effect_outside_scope",
             "policy_gate_in_adapter": "governance_in_adapter", "idempotency_disabled": "duplicate_effect",
             "observation_coupled": "false_reconciled_success", "divergence_rewritten": "detection_or_outcome_mismatch"}
KILLING = ("L1", "L3", "T1", "T2", "T3")
SUB_PER_PRIM = 100
APPROVAL_SYSTEMS = ("ERP", "REGISTRY")


def pick_subset(seed: int, per_prim: int = SUB_PER_PRIM, extra: int = 600, pool: int = 6000) -> list[dict]:
    """Frozen subset: per_prim cases for each killing primitive (observable systems), per_prim approval-probe cases (ERP/REGISTRY with a
    DENIED approval_required request), then `extra` cases spread over the remaining primitives. Deterministic from the seed."""
    params, _ = draw_params(seed + 99, pool, "byz")
    st: dict = {}
    out, used = [], set()

    def take(pred, n):
        got = 0
        for p in params:
            if got >= n:
                break
            if p["idx"] in used or not pred(p):
                continue
            c = build_case(p, seed + 99, st)
            if c is None or not pred(c):
                continue
            used.add(p["idx"])
            out.append(c)
            got += 1
    for prim in KILLING:
        take(lambda p, q=prim: p["main"] == q and p["system"] in ("WMS", "ERP", "REGISTRY") and not p["crash"], per_prim)
    take(lambda p: p["system"] in APPROVAL_SYSTEMS and (p.get("requests") is None or p["requests"][0]["expect"] == "approval")
         and p["denied"], per_prim)
    rest = [q for q in ("L2", "R1", "R2", "O1", "O2", "G1", "G2", "G3")]
    take(lambda p: p["main"] in rest, extra)
    return out


def _run_build(factory, vname, subset, d: Path, seed: int, mutant) -> dict:
    d.mkdir(parents=True, exist_ok=True)
    pair = worlds.Pair(d, "r3m")                       # own ExternalWorld pair (byz + twin), own RunCtx/tick, own work dir
    try:
        sysseed = pair.sysseed
        ctx = RunCtx(pair.ctl, str(d / "ext"), "mutation", vname, tempfile.mkdtemp(prefix="h28-mut-", dir=str(d)))
        pair.attach(ctx)
        variant = factory((mutant,) if mutant else ())
        with (d / RAW).open("w") as fh:
            for c in subset:
                for r in (run_case(ctx, variant, c, "byz"), run_case(ctx, variant, c, "twin")):
                    fh.write(json.dumps(r, default=str) + "\n")
        # case defs are needed by aggregate (observer fault flag): store them once
        with (d / RAW).open("a") as fh:
            for c in subset:
                fh.write(json.dumps({"case_def": {k: c.get(k) for k in ("id", "kind", "domain", "system", "op", "prims", "crash", "fault")}}) + "\n")
    finally:
        pair.close()
    J = finalize.judge_all(d, str(d / "ext"), {"sysseed": sysseed}, str(d / worlds.TWIN_DIR))
    agg = finalize.aggregate(J)
    return {"agg": agg, "rows": J["rows"]}


_JOB: dict = {}


def _build_job(name):
    """Worker body (forked child): one build (None = clean). An unbuilt mutant is 'not killed', never a crash of the run."""
    j = _JOB
    try:
        return name, _run_build(j["factory"], j["vname"], j["subset"], j["base"] / (name or "clean"), j["seed"], name), None
    except Exception as exc:  # noqa: BLE001
        return name, None, f"{type(exc).__name__}: {exc}"


def prove(factory, vname: str, seed: int, workroot: str, per_prim: int = SUB_PER_PRIM, extra: int = 600, workers: int | None = None) -> dict:
    """The clean build and every mutant build are INDEPENDENT (own ExternalWorlds, clock, tick, work dir; the same frozen subset), so they run
    in parallel forked processes; results are collected by name, so the output is byte-identical to the sequential form."""
    subset = pick_subset(seed, per_prim, extra)
    names = [None, *mutants.KNOWN["H28"]]
    _JOB.update(factory=factory, vname=vname, subset=subset, base=Path(workroot), seed=seed)
    n = max(1, min(workers or int(os.environ.get("R3_H28_WORKERS", "0")) or (os.cpu_count() or 2), len(names)))
    if n == 1:
        res = [_build_job(x) for x in names]
    else:
        with multiprocessing.get_context("fork").Pool(n) as pool:
            res = pool.map(_build_job, names, chunksize=1)
    got = {name: (m, err) for name, m, err in res}
    if got[None][1]:
        raise RuntimeError(f"clean build failed: {got[None][1]}")
    clean = got[None][0]
    out = {"_subset": {"cases": len(subset), "per_primitive": per_prim, "ids": [c["id"] for c in subset]}}
    for name in mutants.KNOWN["H28"]:
        m, err = got[name]
        if err:
            out[name] = {"error": err, "own_class": OWN_CLASS[name], "own_class_count": 0,
                         "clean_count": 0, "killed": False, "case_ids": []}
            continue
        out[name] = _kill(name, m, clean)
    return out


def _own(agg: dict, rows: list, name: str) -> tuple[int, list]:
    cls = OWN_CLASS[name]
    if cls == "detection_or_outcome_mismatch":
        miss = [r["case"] for r in rows if r["detect"][0] > r["detect"][1] or r["classes"].get("outcome_mismatch")]
        return len(miss), sorted(miss)
    ids = [r["case"] for r in rows if r["classes"].get(cls)]
    return sum(r["classes"].get(cls, 0) for r in rows) + (len(agg["unattributed_scope_rows"]) if cls == "effect_outside_scope" else 0), sorted(ids)


def _kill(name: str, m: dict, clean: dict) -> dict:
    n, ids = _own(m["agg"], m["rows"], name)
    c, cids = _own(clean["agg"], clean["rows"], name)
    return {"own_class": OWN_CLASS[name], "own_class_count": n, "case_ids": ids, "clean_count": c, "clean_case_ids": cids,
            "killed": n > 0 and c == 0, "all_classes": {k: v["count"] for k, v in m["agg"]["classes"].items()},
            "harness": m["agg"]["harness"]}
