"""Run phase of one variant (inside the sandbox): draw the corpus, build oracle-backed cases, run every Byzantine case twice (byz and
honest twin) plus the honest controls, append RAW records to cases.jsonl. No classification here (the ledger is only readable by the
oracle after ExternalWorld closes: judge/finalize do that)."""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

from r3_shared.extworld import ExternalClient

from . import specs
from .caserun import RunCtx, run_case
from .gen_case import build_case
from .gen_params import draw_params

FILES = ("byzantine-adapter-corpus.json", "external-effect-diff.json", "observation-independence.json",
         "adapter-governance-audit.json", "mutation-results.json")
RAW = "cases.jsonl"


def seed_external(ctl) -> dict:
    """ExternalWorld starting state from the SAME frozen worlds (written once per run; the oracle replays from this seed)."""
    seed = {}
    for d in specs.DOMAINS:
        seed.update(specs.sysstate_seed(d, specs.load(d)[0]))
    for (s, k), v in sorted(seed.items()):
        ctl.seed(s, k, v)
    return {f"{s}|{k}": v for (s, k), v in sorted(seed.items())}


def _dump(path: Path, rows) -> None:
    with path.open("a") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True, separators=(",", ":"), default=str) + "\n")


def run_variant(factory, vname: str, out: Path, exp_id: str, seed: int, ext_sock: str, ext_ctl: str, ext_dir: str, *,
                anchor_sock: str | None = None, cases: int = 5600, controls: int = 1000, start: int = 0, observer_factory=None,
                mutants=(), progress=None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    raw = out / RAW
    if raw.exists():
        raise FileExistsError(f"refusing to overwrite {raw}")
    ctl = ExternalClient(ext_sock, ext_ctl)
    sysseed = seed_external(ctl)
    variant = factory(tuple(mutants))
    work = tempfile.mkdtemp(prefix="h28-run-")
    ctx = RunCtx(ctl, ext_dir, exp_id, vname, work, anchor_sock)
    ctx.observer_factory = observer_factory
    byz, st1 = draw_params(seed, cases, "byz", start)
    ctl_p, st2 = draw_params(seed + 1, controls, "control", start)
    stats = {"hypothesis": {"byz": st1, "control": st2}, "generator": {}, "cases_built": 0, "controls_built": 0}
    t0 = time.time()
    for n, p in enumerate(byz + ctl_p):
        c = build_case(p, seed, stats["generator"])
        if c is None:
            _dump(raw, [{"harness_row": "generator_redraw_exhausted", "case": f"{p['kind']}-{p['idx']:06d}", "domain": p["domain"],
                         "system": p["system"], "kind": p["kind"]}])
            continue
        c["_case"] = {k: c[k] for k in ("id", "kind", "domain", "system", "op", "prims", "k", "reps", "via", "crash", "fault", "replay",
                                       "approved_flow", "denied", "requests", "steps")}
        rows = [{"case_def": c["_case"]}]
        rows.append(run_case(ctx, variant, c, "byz" if p["kind"] == "byz" else "byz"))
        if p["kind"] == "byz":
            rows.append(run_case(ctx, variant, c, "twin"))
            stats["cases_built"] += 1
        else:
            stats["controls_built"] += 1
        _dump(raw, rows)
        if progress and n % 100 == 0:
            progress(n, time.time() - t0)
    return {"seed": seed, "variant": vname, "sysseed": sysseed, "stats": stats, "end_tick": ctx.tick, "cases": cases,
            "controls": controls, "start": start, "duration_s": round(time.time() - t0, 1), "mutants": list(mutants)}
