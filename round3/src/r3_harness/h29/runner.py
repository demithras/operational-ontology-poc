"""Run phase of one variant: draw the corpus (strata env / ctrl / bnd), execute every sequence through the host process, append RAW
records to cases.jsonl. Workers are SPAWNED processes (start method asserted), each with its OWN service set (a service has one tick), each
sequence fully independent: base tick = f(global index) only, deployment ids = f(exp, variant, sequence id), so the evidence bytes do not
depend on the number of workers (serial-vs-parallel byte identity). No classification here (the judge runs after the services close)."""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import time
from pathlib import Path

from . import gen, specs
from .driver import Run
from .services import Services

STRATA = ("env", "ctrl", "bnd")
BASE0, STRIDE = 1000, 400
RAW = "cases.jsonl"


def jobs(n_env: int, n_ctrl: int, n_bnd: int) -> list:
    return [("env", i) for i in range(n_env)] + [("ctrl", i) for i in range(n_ctrl)] + [("bnd", i) for i in range(n_bnd)]


def base_of(j: int) -> int:
    return BASE0 + STRIDE * j


def services_for(root: str, i: int) -> Services:
    r = Path(root)
    return Services(str(r / f"anchor-{i}.sock"), str(r / f"ext-{i}.sock"), str(r / f"ext-{i}.sock.ctl"), str(r / f"ext-{i}"),
                    str(r / f"auth-{i}.sock"), str(r / f"auth-{i}.sock.ctl"), str(r / f"anchor-{i}"), str(r / f"auth-{i}"))


def seed_external(svc: Services) -> dict:
    seed = {}
    for d in specs.DOMAINS:
        seed.update(specs.sysstate_seed(d, specs.load(d)[0]))
    for (s, k), v in sorted(seed.items()):
        svc.ext.seed(s, k, v)
    return {f"{s}|{k}": v for (s, k), v in sorted(seed.items())}


def run_jobs(svc: Services, variant: str, mutants, exp_id: str, seed: int, my_jobs: list, out_path: Path, workroot: str,
             extra_paths=(), progress=None) -> dict:
    """Execute my_jobs [(global_index, stratum, idx)] in order on one service set; append JSON lines to out_path."""
    gstats, t0 = {}, time.time()
    with out_path.open("a") as fh:
        for n, (j, stratum, idx) in enumerate(my_jobs):
            seq = gen.build(stratum, idx, seed, gstats)
            if seq is None:
                row = {"seq": f"{stratum}-{idx:06d}", "stratum": stratum, "variant": variant, "harness": [{"row": "generator_redraw_exhausted"}],
                       "j": j, "events": [], "unsupported": 0, "deploy_error": None}
            else:
                try:
                    row = Run(svc, variant, mutants, seq, exp_id, base_of(j), workroot, extra_paths).run()
                except Exception as exc:  # noqa: BLE001
                    row = {"seq": seq["id"], "stratum": stratum, "variant": variant, "harness": [{"row": "worker_exception", "detail": f"{type(exc).__name__}: {exc}"[:300]}],
                           "j": j, "events": [], "unsupported": 0, "deploy_error": None}
                row["seq_def"] = seq
            row["j"] = j
            fh.write(json.dumps(row, sort_keys=True, separators=(",", ":"), default=str) + "\n")
            fh.flush()
            if progress and n % 10 == 0:
                progress(n, len(my_jobs), time.time() - t0)
    return gstats


def _worker(root, i, variant, mutants, exp_id, seed, my_jobs, out, workroot, extra, q):
    svc = services_for(root, i)
    try:
        q.put((i, run_jobs(svc, variant, mutants, exp_id, seed, my_jobs, Path(out), workroot, extra), None))
    except BaseException as exc:  # noqa: BLE001
        q.put((i, {}, f"{type(exc).__name__}: {exc}"))


def run_variant(root: str, variant: str, vname: str, out: Path, exp_id: str, seed: int, n_env: int, n_ctrl: int, n_bnd: int, workers: int,
                mutants=(), extra_paths=(), workroot: str | None = None, in_process: bool = False, job_list=None) -> dict:
    """root = the service-set directory (anchor-i / ext-i / auth-i for i < max(workers,1)). Returns run-pre."""
    if mp.get_start_method(allow_none=True) not in (None, "spawn") and not in_process:
        raise RuntimeError("multiprocessing start method must be 'spawn'")
    out.mkdir(parents=True, exist_ok=True)
    raw = out / RAW
    if raw.exists():
        raise FileExistsError(f"refusing to overwrite {raw}")
    W = max(1, workers)
    allj = [(j, s, i) for j, (s, i) in enumerate(job_list if job_list is not None else jobs(n_env, n_ctrl, n_bnd))]
    sysseed = None
    for i in range(W):
        sysseed = seed_external(services_for(root, i))
    work = workroot or str(out / ".work")
    Path(work).mkdir(parents=True, exist_ok=True)
    t0, gstats, errors = time.time(), {}, []
    frag = [out / f"{RAW}.w{i}" for i in range(W)]
    if in_process:
        gstats = run_jobs(services_for(root, 0), variant, mutants, exp_id, seed, allj, frag[0], work, extra_paths)
    else:
        ctx = mp.get_context("spawn")
        q = ctx.Queue()
        ps = [ctx.Process(target=_worker, args=(root, i, variant, tuple(mutants), exp_id, seed, allj[i::W], str(frag[i]), work,
                                                tuple(extra_paths), q)) for i in range(W)]
        for p in ps:
            p.start()
        for _ in ps:
            i, gs, err = q.get()
            errors += [f"worker {i}: {err}"] if err else []
            for k, v in gs.items():
                gstats[k] = gstats.get(k, 0) + v if isinstance(v, int) else v
        for p in ps:
            p.join()
    rows = []
    for f in frag:
        if f.exists():
            rows += [json.loads(l) for l in f.read_text().splitlines()]
            f.unlink()
    rows.sort(key=lambda r: r["j"])
    with raw.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True, separators=(",", ":"), default=str) + "\n")
    return {"seed": seed, "variant": vname, "sysseed": sysseed, "workers": W, "sizes": {"env": n_env, "ctrl": n_ctrl, "bnd": n_bnd},
            "gen_stats": gstats, "errors": errors, "rows": len(rows), "duration_s": round(time.time() - t0, 1), "mutants": list(mutants)}
