#!/usr/bin/env python
"""H28 Byzantine-adapter experiment, ONE entry point for dev, smoke and official runs (G3-E31b: only ids and sizes differ).
Two modes, both driven by scripts/run_h28.sh:
  run       inside the sandbox: needs the launcher's ExternalWorld (R3_EXT_*) and anchor (R3_ANCHOR_*); writes cases.jsonl + run-pre.json
  finalize  after both servers were closed: oracle reads the closed ledger, judge, mutation proof, audit, five evidence files, manifest
A NON-DEV id REFUSES (exit 2, no evidence written) when ExternalWorld or the anchor is unreachable, HEAD != the candidate tag, the
FREEZE_G4 hashes mismatch, the out dir exists, or sizes are below the frozen floors. Fakes only with --test-variants (never registered)."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROUND3 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROUND3 / "src"))

from r3_harness.h28 import audit, evaluator, evidence_out, finalize, mutation, runner, selftest  # noqa: E402
from r3_shared.extworld import ExternalError, is_dev_id, require_external  # noqa: E402
from r3_harness.h28.factories import NamedFactory  # noqa: E402
from r3_shared.registry import load_variant  # noqa: E402

FROZEN = {"cases": 5600, "controls": 1000}
FACTOR = 0.5


def die(msg: str, code: int = 2):
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def factory_for(name: str, test_variants: bool):
    if name.startswith("fake-"):
        if not test_variants:
            die(f"{name}: fake variants need --test-variants")
        sys.path.insert(0, str(ROUND3))
        from tests.fakes import fake_h28
        return NamedFactory(name), None
    try:
        load_variant(name)
    except NotImplementedError as exc:
        die(f"not implemented yet - G4 ({exc})")
    return NamedFactory(name), name


def overrides_for(cases: int, controls: int) -> dict:
    """Dev-size stamped overrides (G3 Q15): the frozen floors scaled to the run size, recorded in the manifest, refused on non-dev ids."""
    if cases >= FROZEN["cases"] and controls >= FROZEN["controls"]:
        return {}
    s = cases / FROZEN["cases"]
    sc = lambda v: max(1, int(v * s * FACTOR))  # noqa: E731
    return {"min_cases": cases, "min_controls": controls, "min_per_primitive": sc(evaluator.FLOORS["min_per_primitive"]),
            "min_per_system": sc(evaluator.FLOORS["min_per_system"]), "min_crash": sc(evaluator.FLOORS["min_crash"]),
            "min_none": sc(evaluator.FLOORS["min_none"]), "min_fault": sc(evaluator.FLOORS["min_fault"]),
            "min_detect_attempts": sc(evaluator.FLOORS["min_detect_attempts"])}


def git(*a):
    return subprocess.check_output(["git", "-C", str(ROUND3), *a], text=True).strip()


def guard(a, out: Path) -> dict:
    ov = overrides_for(a.cases, a.controls)
    dev = is_dev_id(a.exp_id)
    if ov and not a.dev_overrides:
        die(f"sizes below the frozen floors ({FROZEN}) need --dev-overrides (dev ids only)")
    if ov and not dev:
        die(f"refusing: size overrides are allowed only for dev experiment ids (containing '-dev'), not {a.exp_id!r}")
    if not dev:
        try:
            require_external(a.exp_id)
        except ExternalError as exc:
            die(str(exc))
        if not (os.environ.get("R3_ANCHOR_SOCK") and os.environ.get("R3_ANCHOR_DIR")):
            die("refusing: non-dev id needs the anchor (R3_ANCHOR_SOCK/R3_ANCHOR_DIR): start it through scripts/run_h28.sh")
        if not a.candidate_tag:
            die("refusing: non-dev id needs --candidate-tag")
        try:
            if git("rev-parse", "HEAD") != git("rev-parse", a.candidate_tag + "^{commit}"):
                die(f"refusing: HEAD != {a.candidate_tag}")
        except subprocess.CalledProcessError:
            die(f"refusing: candidate tag {a.candidate_tag} not found")
        frozen, cur = evaluator.freeze_state()
        drift = [f for f, h in frozen.items() if cur.get(f) != h]
        if drift:
            die(f"refusing: FREEZE_G4 hashes mismatch: {drift}")
        fz_hash, cur_hash = evaluator.catalogue_state()
        if fz_hash is None:
            die(f"refusing: adapter catalogue {evaluator.CATALOGUE_REL} is not frozen in FREEZE_G4 (the evaluator would mark the run INVALID)")
        if fz_hash != cur_hash:
            die(f"refusing: adapter catalogue {evaluator.CATALOGUE_REL} sha256 != FREEZE_G4")
        if (out / "cases.jsonl").exists() or (out / "run-pre.json").exists():
            die(f"refusing: {out} already holds evidence")
    return ov


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("run", "finalize"))
    ap.add_argument("--exp-id", required=True)
    ap.add_argument("--variant", required=True)
    ap.add_argument("--seed", type=int, default=2811)
    ap.add_argument("--cases", type=int, default=FROZEN["cases"])
    ap.add_argument("--controls", type=int, default=FROZEN["controls"])
    ap.add_argument("--dev-overrides", action="store_true")
    ap.add_argument("--candidate-tag", default=None)
    ap.add_argument("--test-variants", action="store_true")
    ap.add_argument("--out-root", default=str(ROUND3 / "experiments" / "h28"))
    ap.add_argument("--mutation-per-prim", type=int, default=mutation.SUB_PER_PRIM)
    ap.add_argument("--mutation-extra", type=int, default=600)
    ap.add_argument("--selftest-cases", type=int, default=60)
    ap.add_argument("--adapter-modules", default=None, help="comma list; default: the variant package's ADAPTER_MODULES declaration")
    ap.add_argument("--closed-ext", default=None)
    ap.add_argument("--closed-ext-twin", default=None)
    ap.add_argument("--closed-anchor", default=None)
    a = ap.parse_args()
    out = Path(a.out_root) / a.exp_id / a.variant
    factory, pkg = factory_for(a.variant, a.test_variants)
    if a.mode == "run":
        ov = guard(a, out)
        sock, ctl, ext = os.environ.get("R3_EXT_SOCK"), os.environ.get("R3_EXT_CTL"), os.environ.get("R3_EXT_DIR")
        if not (sock and ctl and ext):
            die("run needs R3_EXT_SOCK/R3_EXT_CTL/R3_EXT_DIR: start it through scripts/run_h28.sh")
        tsock, tctl, tdir = os.environ.get("R3_EXT_TWIN_SOCK"), os.environ.get("R3_EXT_TWIN_CTL"), os.environ.get("R3_EXT_TWIN_DIR")
        if not (tsock and tctl and tdir):
            die("run needs the TWIN ExternalWorld (R3_EXT_TWIN_SOCK/CTL/DIR, G4-E26): start it through scripts/run_h28.sh")
        pre = runner.run_variant(factory, a.variant, out, a.exp_id, a.seed, sock, ctl, ext, twin_sock=tsock, twin_ctl=tctl, twin_dir=tdir, anchor_sock=None if a.variant.startswith("fake-") else os.environ.get("R3_ANCHOR_SOCK"),
                                 cases=a.cases, controls=a.controls)
        pre["dev_overrides"] = ov
        (out / "run-pre.json").write_text(json.dumps(pre, sort_keys=True))
        print(f"{a.variant}: run complete ({pre['stats']['cases_built']} byzantine, {pre['stats']['controls_built']} controls)")
        return 0
    pre = json.loads((out / "run-pre.json").read_text())
    J = finalize.judge_all(out, str(out / "ext"), pre, str(out / "ext-twin"))
    agg = finalize.aggregate(J)
    inst = factory(())
    built = getattr(inst, "adapter_modules", None)       # G4-E20: the adapter modules of the BUILD under test (incl. mutant-only modules)
    mods = a.adapter_modules.split(",") if a.adapter_modules else (list(built) if built else
           (audit.declared_adapter_modules(ROUND3 / "src" / pkg) if pkg else None))
    work = tempfile.mkdtemp(prefix="h28-fin-")
    st = None
    try:
        sys.path.insert(0, str(ROUND3))
        from tests.fakes import fake_h28
        st = selftest.run(lambda m: fake_h28.load("FakeHonest", m), lambda m: fake_h28.load("FakeAdapterPolicy", m),
                          "tests.fakes.fake_h28_policy", ["tests.fakes.fake_h28_adapt"], a.seed, a.selftest_cases, work + "/st")
    except ImportError as exc:
        st = {"run": False, "error": f"fakes unavailable: {exc}"}
    gov_audit = audit.build_audit(J, a.variant, mods, st)
    mut = mutation.prove(factory, a.variant, a.seed, work + "/mut", a.mutation_per_prim, a.mutation_extra)
    hashes = evidence_out.write_all(out, J, agg, pre, gov_audit, mut)
    closes = {"external": json.loads(a.closed_ext) if a.closed_ext else None,
              "external_twin": json.loads(a.closed_ext_twin) if a.closed_ext_twin else None, "anchor": json.loads(a.closed_anchor) if a.closed_anchor else None}
    evidence_out.seal(out, a.exp_id, a.variant, pre, hashes, closes, pkg, pre.get("dev_overrides") or {}, {"generator_stats": pre["stats"]})
    c = {k: v["count"] for k, v in agg["classes"].items()}
    print(f"{a.variant}: finalized classes={c} detection={agg['detection']} harness={agg['harness']} sysstate_ok={agg['sysstate']['replay_equals_sysstate']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
