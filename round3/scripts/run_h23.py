#!/usr/bin/env python
"""Run the H23 adversarial experiment per variant and write evidence to experiments/h23/<exp-id>/<variant>/.

Fake variants (tests/fakes) are selectable ONLY with --test-variants and are never registered.
Unimplemented real variants: prints "not implemented yet - P2" and exits 2.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
import time
from pathlib import Path

ROUND3 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROUND3 / "src"))

from r3_harness.h23 import differential  # noqa: E402
from r3_harness.h23.runner import FILES, run_variant  # noqa: E402
from r3_shared.registry import load_variant  # noqa: E402


def load_fakes():
    spec = importlib.util.spec_from_file_location("h23_fakes", ROUND3 / "tests" / "fakes" / "h23_fakes.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp-id", required=True)
    ap.add_argument("--variants", default="paladin,conventional")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--sequences", type=int, default=10000)
    ap.add_argument("--mutation-sequences", type=int, default=150)
    ap.add_argument("--skip-differential", action="store_true", help="do not write variant-differential.json")
    ap.add_argument("--test-variants", action="store_true", help="allow fake-* variants from tests/fakes")
    ap.add_argument("--out-root", default=str(ROUND3 / "experiments" / "h23"))
    a = ap.parse_args()
    fakes = load_fakes() if a.test_variants else None
    ran: list[tuple[str, object]] = []
    for name in a.variants.split(","):
        if name.startswith("fake-"):
            if fakes is None:
                print(f"{name}: fake variants need --test-variants", file=sys.stderr)
                return 2
            factory, pkg = (lambda m, n=name: fakes.load(n, m)), None
        else:
            try:
                load_variant(name)  # fail early (NotImplementedError) before any run
                factory, pkg = (lambda m, n=name: load_variant(n, m)), name
            except NotImplementedError as exc:
                print(f"not implemented yet - P2 ({exc})", file=sys.stderr)
                return 2
        out = Path(a.out_root) / a.exp_id / name
        if out.exists():
            print(f"refusing to overwrite {out}", file=sys.stderr)
            return 2
        t0 = time.perf_counter()
        r = run_variant(factory, name, out, a.exp_id, a.seed, a.sequences, a.mutation_sequences, pkg)
        an = r["analysis"]
        print(f"{name}: sequences={an['sequences']} unique={an['unique_sequences']} calls={an['calls']} "
              f"classes={an['class_counts']} elapsed={time.perf_counter() - t0:.1f}s")
        ran.append((name, factory))
    if len(ran) >= 2 and not a.skip_differential:  # R-5: same recorded corpus replayed on every other variant
        root = Path(a.out_root) / a.exp_id
        ref_name, ref_factory = ran[0]
        records = differential.load_records(root / ref_name / FILES[0])
        pairs = []
        for name, factory in ran[1:]:
            replayed = differential.replay(factory(()), records)
            pairs.append(differential.compare(records, replayed, ref_name, name))
            print(f"differential {ref_name} vs {name}: {pairs[-1]['differing_calls']} differing of {pairs[-1]['calls_compared']} calls")
        differential.write_report(root / "variant-differential.json", pairs, a.seed, a.sequences)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
