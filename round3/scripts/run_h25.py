#!/usr/bin/env python
"""Run the H25 experiment per variant and write evidence to experiments/h25/<exp-id>/<variant>/.

Fake variants (tests/fakes/h25_fakes.py) are selectable ONLY with --test-variants and are never registered.
Unimplemented real variants: prints "not implemented yet - G3" and exits 2."""
from __future__ import annotations

import argparse
import importlib.util
import sys
import time
from pathlib import Path

ROUND3 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROUND3 / "src"))
sys.path.insert(0, str(ROUND3))

from r3_harness.h25.runner import run_variant  # noqa: E402
from r3_shared.registry import load_variant  # noqa: E402

MUTANT_FAKE = {"precedence_inverted": "fake-precinverted", "quorum_weakened": "fake-quorumweak",
               "emergency_no_expiry": "fake-noexpiry", "merit_autofill": "fake-autofill",
               "domain_privilege_branch": "fake-domainbranch"}


def load_fakes():
    spec = importlib.util.spec_from_file_location("h25_fakes", ROUND3 / "tests" / "fakes" / "h25_fakes.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["h25_fakes"] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp-id", required=True)
    ap.add_argument("--variants", default="paladin,conventional")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--cases", type=int, default=9000, help="sequential cases per variant (+ races + nogov = unique total)")
    ap.add_argument("--races", type=int, default=1100, help="concurrent race cases per variant (official: >= 1000)")
    ap.add_argument("--nogov", type=int, default=100)
    ap.add_argument("--mutation-cases", type=int, default=120)
    ap.add_argument("--mutation-races", type=int, default=40)
    ap.add_argument("--audit-cases", type=int, default=1000, help="renaming-audit sample (official: >= 1000)")
    ap.add_argument("--boundary-cases", type=int, default=1000, help="merit-invariance and judgment-flip probes (official: >= 1000 each)")
    ap.add_argument("--test-variants", action="store_true", help="allow fake-* variants from tests/fakes")
    ap.add_argument("--out-root", default=str(ROUND3 / "experiments" / "h25"))
    a = ap.parse_args()
    fakes = load_fakes() if a.test_variants else None
    try:
        ref = (fakes or load_fakes()).load("fake-honest")
    except Exception:  # noqa: BLE001 - no tests dir: the oracle self-test is then recorded as unavailable
        ref = None
    for name in a.variants.split(","):
        keep, scan = (), None
        if name.startswith("fake-"):
            if fakes is None:
                print(f"{name}: fake variants need --test-variants", file=sys.stderr)
                return 2
            factory = (lambda m, n=name: fakes.load(MUTANT_FAKE[m[0]] if m else n))
            pkg, keep, scan = None, ("admin",), fakes.load(name).sources
        else:
            try:
                import inspect
                if "governance" not in inspect.signature(load_variant(name).deploy).parameters:
                    raise NotImplementedError("deploy(governance=...) missing")
                factory, pkg = (lambda m, n=name: load_variant(n, m)), name
            except NotImplementedError as exc:
                print(f"not implemented yet - G3 ({exc})", file=sys.stderr)
                return 2
        out = Path(a.out_root) / a.exp_id / name
        if out.exists():
            print(f"refusing to overwrite {out}", file=sys.stderr)
            return 2
        t0 = time.perf_counter()
        r = run_variant(factory, name, out, a.exp_id, a.seed, a.cases, a.races, a.nogov, a.mutation_cases, a.mutation_races,
                        a.audit_cases, a.boundary_cases, pkg, keep, scan, ref)
        an = r["analysis"]
        print(f"{name}: cases={an['cases']} unique={an['unique_cases']} actions={an['actions']} races={an['race_cases']} "
              f"classes={an['class_counts']} elapsed={time.perf_counter() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
