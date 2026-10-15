"""Audit self-test (PROT-H28 R28-12): the `policy_gate_in_adapter` build must be flagged by BOTH the behavioural check and the static
scan; the oracle-backed FakeHonest must report 0. The fakes live under tests/ (never registered); the caller passes factories and
the dotted adapter-side module names so r3_harness never imports tests."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from . import audit, finalize, specs, worlds
from .caserun import RunCtx, run_case
from .mutation import APPROVAL_SYSTEMS
from .gen_case import build_case
from .gen_params import draw_params
from .runner import RAW, seed_external


def _probe_cases(seed: int, n: int) -> list[dict]:
    params, _ = draw_params(seed + 7, 4000, "byz")
    st, out = {}, []
    for p in params:
        if len(out) >= n:
            break
        if p["system"] in APPROVAL_SYSTEMS and p["denied"] and not p["crash"]:
            c = build_case(p, seed + 7, st)
            if c is not None and c["requests"][0]["expect"] == "approval":
                out.append(c)
    return out


def behavioural(factory, seed: int, n: int, workdir: Path) -> dict:
    d = Path(workdir)
    d.mkdir(parents=True, exist_ok=True)
    pair = worlds.Pair(d, "r3st")
    try:
        sysseed = pair.sysseed
        ctx = RunCtx(pair.ctl, str(d / "ext"), "selftest", "selftest", tempfile.mkdtemp(prefix="h28-st-", dir=str(d)))
        pair.attach(ctx)
        v = factory(())
        cases = _probe_cases(seed, n)
        with (d / RAW).open("w") as fh:
            for c in cases:
                for r in (run_case(ctx, v, c, "byz"), run_case(ctx, v, c, "twin")):
                    fh.write(json.dumps(r, default=str) + "\n")
            for c in cases:
                fh.write(json.dumps({"case_def": {k: c.get(k) for k in ("id", "kind", "domain", "system", "op", "prims", "crash", "fault")}}) + "\n")
    finally:
        pair.close()
    J = finalize.judge_all(d, str(d / "ext"), {"sysseed": sysseed}, str(d / worlds.TWIN_DIR))
    return {"cases": len(cases), "governance_in_adapter": sum(r["classes"].get("governance_in_adapter", 0) for r in J["rows"]),
            "oracle_denied_variant_ok": sum(1 for r in J["rows"] for g in r["gov"] if g["sub"] == "oracle_denied_variant_ok")}


def run(honest_factory, policy_factory, policy_module: str, honest_modules: list[str], seed: int, n: int, workdir: str) -> dict:
    lits = audit.all_literals()
    st_pol = audit.static_scan("selftest-policy", [policy_module], lits, resolutions={})
    st_hon = audit.static_scan("selftest-honest", honest_modules, lits, resolutions={})
    b_pol = behavioural(policy_factory, seed, n, Path(workdir) / "policy")
    b_hon = behavioural(honest_factory, seed, n, Path(workdir) / "honest")
    return {"run": True, "policy_gate_in_adapter": {"behavioural": b_pol, "static_hits": st_pol["unresolved_count"]},
            "honest_reference": {"behavioural": b_hon, "static_hits": st_hon["unresolved_count"]},
            "ok": b_pol["governance_in_adapter"] > 0 and st_pol["unresolved_count"] > 0 and b_hon["governance_in_adapter"] == 0
                  and st_hon["unresolved_count"] == 0}
