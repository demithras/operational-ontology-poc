#!/usr/bin/env python
"""H29 safe-continuity experiment, ONE entry point for dev, smoke and official runs (G3-E31b: only ids and sizes differ). Two modes, both
driven by scripts/run_h29.sh:
  run       inside the sandbox: needs the launcher's service sets (R3_H29_SVC, R3_H29_WORKERS); writes cases.jsonl + run-pre.json
  finalize  after all services were closed: oracle reads the closed ledgers/logs, judge, mutation proof, evidence files, manifest
A NON-DEV id REFUSES (exit 2, no evidence written) per r3_harness.h29.launch.guard. Fakes only with --test-variants (never registered)."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROUND3 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROUND3 / "src"))

from r3_harness.h29 import evalchecks as EC, evidence_out, finalize, launch, mutation, reasonmap, runner  # noqa: E402


def die(msg: str, code: int = 2):
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def variant_spec(name: str, test_variants: bool) -> tuple[str, str | None, tuple]:
    """-> (host variant string, candidate package for the manifest hash, extra sys.path entries)."""
    if ":" in name:
        if not test_variants:
            die(f"{name}: fake variants need --test-variants")
        return name, None, (str(ROUND3),)
    from r3_shared.registry import load_variant
    try:
        load_variant(name)
    except NotImplementedError as exc:
        die(f"not implemented yet - G5 ({exc})")
    return name, name, ()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("run", "finalize"))
    ap.add_argument("--exp-id", required=True)
    ap.add_argument("--variant", required=True)
    ap.add_argument("--seed", type=int, default=2911)
    ap.add_argument("--sequences", type=int, default=EC.SIZES["env"])
    ap.add_argument("--controls", type=int, default=EC.SIZES["ctrl"])
    ap.add_argument("--boundary", type=int, default=EC.SIZES["bnd"])
    ap.add_argument("--dev-overrides", action="store_true")
    ap.add_argument("--candidate-tag", default=None)
    ap.add_argument("--test-variants", action="store_true")
    ap.add_argument("--mutants", action="store_true", help="finalize: run the mutation proof (all KNOWN['H29'] builds)")
    ap.add_argument("--mutation-env", type=int, default=1400)
    ap.add_argument("--out-root", default=str(ROUND3 / "experiments" / "h29"))
    ap.add_argument("--closed", default=None, help="finalize: JSON of the services' close() outputs")
    ap.add_argument("--workers", type=int, default=int(os.environ.get("R3_H29_WORKERS", "0") or 0))
    a = ap.parse_args(argv)
    out = Path(a.out_root) / a.exp_id / a.variant.split(":")[-1]
    host_name, pkg, extra = variant_spec(a.variant, a.test_variants)
    vname = a.variant.split(":")[-1]
    if a.mode == "run":
        try:
            ov = launch.guard(a, out)
        except launch.Refusal as exc:
            die(str(exc))
        root, W = os.environ.get("R3_H29_SVC"), max(1, int(os.environ.get("R3_H29_WORKERS", "1") or 1))
        if not root:
            die("run needs R3_H29_SVC / R3_H29_WORKERS: start it through scripts/run_h29.sh")
        pre = runner.run_variant(root, host_name, vname, out, a.exp_id, a.seed, a.sequences, a.controls, a.boundary, W, extra_paths=extra)
        pre.update(dev_overrides=ov, candidate=launch.candidate_record(a))
        (out / "run-pre.json").write_text(json.dumps(pre, sort_keys=True))
        print(f"{vname}: run complete ({pre['rows']} sequences, {pre['duration_s']} s, workers {W})")
        return 0
    pre = json.loads((out / "run-pre.json").read_text())
    closes = json.loads(a.closed) if a.closed else {}
    W = pre["workers"]
    J = finalize.judge_all(out, out / "svc", W, pre, closes, reasonmap.for_variant(vname))
    mut = {}
    if a.mutants:
        work = tempfile.mkdtemp(prefix="h29m", dir="/tmp")
        mut = mutation.prove(host_name, vname, a.seed, min(a.mutation_env, a.sequences), W, Path(work), extra, J["rows"])
    hashes = evidence_out.write_all(out, J, pre, mut)
    evidence_out.seal(out, a.exp_id, vname, pre, hashes, closes, pkg, pre.get("dev_overrides") or {}, {"candidate": pre.get("candidate"), "generator_stats": pre["gen_stats"]})
    c = {k: v["count"] for k, v in J["agg"]["classes"].items() if v["count"]}
    print(f"{vname}: finalized classes={c} harness={J['agg']['harness']} sysstate_ok={J['sysstate']['replay_equals_sysstate']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
