#!/usr/bin/env python
"""H27 provenance experiment. Two modes (scripts/run_h27.sh drives both, the first under run_sandboxed.sh):
  run       inside the sandbox: needs R3_ANCHOR_SOCK/R3_ANCHOR_DIR; writes the evidence files of one variant
  finalize  after the anchor closed: E2/E5 audit + envelope.json
Fake variants (tests/fakes) only with --test-variants, never registered. Unbuilt real variants: "not implemented yet - G2", exit 2."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROUND3 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROUND3 / "src"))

from r3_harness.h27 import audit, mutation, runner  # noqa: E402
from r3_shared.registry import load_variant  # noqa: E402


def factory_for(name: str, test_variants: bool):
    if name.startswith("fake-"):
        if not test_variants:
            print(f"{name}: fake variants need --test-variants", file=sys.stderr)
            raise SystemExit(2)
        sys.path.insert(0, str(ROUND3))
        from tests.fakes import fake_h27
        return (lambda m, n=name: fake_h27.load(n, m)), None
    try:
        load_variant(name)
    except NotImplementedError as exc:
        print(f"not implemented yet - G2 ({exc})", file=sys.stderr)
        raise SystemExit(2)
    return (lambda m, n=name: load_variant(n, m)), name


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("run", "finalize"))
    ap.add_argument("--exp-id", required=True)
    ap.add_argument("--variant", required=True)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--per-domain", type=int, default=300, help="base histories per domain (official: >= 300)")
    ap.add_argument("--tamper-cases", type=int, default=5000)
    ap.add_argument("--controls", type=int, default=1000)
    ap.add_argument("--decisions-min", type=int, default=5)
    ap.add_argument("--decisions-max", type=int, default=30)
    ap.add_argument("--mutation-bases", type=int, default=mutation.SUB_BASES)
    ap.add_argument("--mutation-cases", type=int, default=mutation.SUB_CASES)
    ap.add_argument("--test-variants", action="store_true")
    ap.add_argument("--out-root", default=str(ROUND3 / "experiments" / "h27"))
    ap.add_argument("--closed-head", default=None, help="finalize: JSON of the head the anchor reported at close")
    a = ap.parse_args()
    out = Path(a.out_root) / a.exp_id / a.variant
    factory, pkg = factory_for(a.variant, a.test_variants)
    if a.mode == "run":
        sock, adir = os.environ.get("R3_ANCHOR_SOCK"), os.environ.get("R3_ANCHOR_DIR")
        if not sock or not adir:
            print("run needs R3_ANCHOR_SOCK/R3_ANCHOR_DIR: start it through scripts/run_h27.sh (run_sandboxed.sh)", file=sys.stderr)
            return 2
        if (out / "envelope.json").exists():
            print(f"refusing to overwrite {out}", file=sys.stderr)
            return 2
        pre = runner.run_variant(factory, a.variant, out, a.exp_id, a.seed, sock, adir, per_domain=a.per_domain,
                                 tamper_cases=a.tamper_cases, controls=a.controls,
                                 decisions=(a.decisions_min, a.decisions_max), mutation_bases=a.mutation_bases,
                                 mutation_cases=a.mutation_cases)
        (out / "run-pre.json").write_text(json.dumps(pre))
        print(f"{a.variant}: run complete")
        return 0
    pre = json.loads((out / "run-pre.json").read_text())
    head = json.loads(a.closed_head) if a.closed_head else None
    au = audit.finalize(audit.load(out / runner.FILES[3]), str(out / "anchor"), head)
    (out / runner.FILES[3]).write_text(json.dumps(au, indent=1, sort_keys=True) + "\n")
    runner.seal(out, a.exp_id, a.variant, pre["seed"], pre, pkg)
    print(f"{a.variant}: finalized E1={au['E1_separate_process']} E2={au['E2_key_only_at_close']} "
          f"E3/E4={au['E3_holds']}({au['E3_enforcement']}) E5={au['E5_log_integrity']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
