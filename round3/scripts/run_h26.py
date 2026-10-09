#!/usr/bin/env python
"""H26 knowledge-sovereignty experiment: run_h26.py --exp-id ID --variants paladin,conventional [--seed N] [--pairs N]
Writes experiments/h26/ID/<variant>/{noninterference-pairs.json(+.jsonl.gz), exfiltration-fuzz.json, tool-schema-disclosure.json,
provenance-redaction.json, mutation-results.json, safe-progress.json, envelope.json}. Fake variants (tests/fakes) only with
--test-variants, never registered. Unbuilt real variants: "not implemented yet - G3", exit 2. Minimum overrides are dev-only
(experiment id must contain '-dev') and are recorded in the envelope. With R3_ANCHOR_SOCK set (run_h26.sh) worlds get a
HistoryStore + AnchorClient (ruling Q10)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROUND3 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROUND3 / "src"))

from r3_harness.h26 import runner  # noqa: E402
from r3_shared.registry import load_variant  # noqa: E402


def factory_for(name: str, test_variants: bool):
    if name.startswith("fake-"):
        if not test_variants:
            print(f"{name}: fake variants need --test-variants", file=sys.stderr)
            raise SystemExit(2)
        sys.path.insert(0, str(ROUND3))
        from tests.fakes import fake_h26
        return (lambda m, n=name: fake_h26.load(n, m)), None
    import inspect
    try:
        v = load_variant(name)
    except NotImplementedError as exc:
        print(f"not implemented yet - G3 ({exc})", file=sys.stderr)
        raise SystemExit(2)
    if "governance" not in inspect.signature(type(v).deploy).parameters or not hasattr(v, "audience") and not hasattr(type(v), "audience"):
        print(f"not implemented yet - G3 ({name}.deploy takes no governance / no audience)", file=sys.stderr)
        raise SystemExit(2)
    return (lambda m, n=name: load_variant(n, m)), name


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp-id", required=True)
    ap.add_argument("--variants", default="paladin,conventional")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--pairs", type=int, default=5000, help="valid pairs per variant (official: >= 5,000)")
    ap.add_argument("--aa", type=int, default=500, help="A/A controls per variant (official: >= 500)")
    ap.add_argument("--fuzz-calls", type=int, default=20000)
    ap.add_argument("--mutation-pairs", type=int, default=60, help="pairs per mutant in the fixed sub-corpus")
    ap.add_argument("--out-root", default=str(ROUND3 / "experiments" / "h26"))
    ap.add_argument("--test-variants", action="store_true")
    a = ap.parse_args()
    ov = {"min_pairs": a.pairs, "min_aa": a.aa, "min_fuzz_calls": a.fuzz_calls}
    frozen = {"min_pairs": 5000, "min_aa": 500, "min_fuzz_calls": 20000}
    rec = {k: v for k, v in ov.items() if v != frozen[k]}
    if rec and "-dev" not in a.exp_id:
        print(f"refusing: counts below the frozen minimums are allowed only for dev ids (containing '-dev'): {rec}", file=sys.stderr)
        return 2
    import os
    import shutil
    import tempfile
    if "-dev" not in a.exp_id and not os.environ.get("R3_ANCHOR_SOCK"):  # G3-E31(b): official runs must carry the sandboxed anchor
        print(f"refusing: non-dev experiment id {a.exp_id!r} requires R3_ANCHOR_SOCK (launch through scripts/run_h26.sh)", file=sys.stderr)
        return 2
    dev_anchor = None
    if "-dev" in a.exp_id and not os.environ.get("R3_ANCHOR_SOCK"):  # ruling Q10: dev paths also run with history + anchor
        from r3_shared.anchor import start_anchor
        td = tempfile.mkdtemp(prefix="h26a-", dir="/tmp")
        dev_anchor = (start_anchor(os.path.join(td, "anchor"), os.path.join(td, "s")), td)
        os.environ["R3_ANCHOR_SOCK"] = dev_anchor[0].sock_path
    try:
        return _run(a, rec)
    finally:
        if dev_anchor:
            try:
                dev_anchor[0].close()
            finally:
                shutil.rmtree(dev_anchor[1], ignore_errors=True)


def _run(a, rec) -> int:
    for name in a.variants.split(","):
        factory, pkg = factory_for(name, a.test_variants)
        out = Path(a.out_root) / a.exp_id / name
        if out.exists():
            print(f"refusing to overwrite {out}", file=sys.stderr)
            return 2
        r = runner.run_variant(factory, name, out, a.exp_id, a.seed, a.pairs, a.aa, a.fuzz_calls, a.mutation_pairs, pkg,
                               overrides=rec)
        print(f"{name}: {r['pairs']} pairs (+A/A) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
