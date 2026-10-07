"""One tamper case or clean control: copy the base files, tamper through TamperView only, deploy a FRESH deployment of
the same variant on the SAME (copied) world store + HistoryStore with the CURRENT specs and an AnchorClient, replay and
explain the sampled decisions, classify (B5), then optionally probe continuation (R27-5)."""
from __future__ import annotations

import copy
import os
import random
import shutil
import time

from r3_oracle import ops_model, provenance as pv
from r3_shared.clock import LogicalClock
from r3_shared.histstore import HistoryStore, TamperView
from r3_shared.variant import g2_call
from r3_shared.world import WorldReader, WorldStore, diff

from . import tamper


class Fresh:
    """The fresh deployment under test (the harness never reuses the generating deployment object)."""

    def __init__(self, base, variant, anchor, world: str, hist: str):
        st = base.stream
        self.store = WorldStore(world, clock=LogicalClock(st.clock.now()), writers=st.writers)
        self.hist = HistoryStore(hist)
        self.reader = WorldReader(world)
        self.dep = variant.deploy(base.domain, self.store.handle_factory(), st.idp.verifier(), st.ops,
                                  base.deploy_auth(), self.store.clock, state_dir=None, history=self.hist, anchor=anchor)

    def close(self):
        self.reader.close()
        self.hist.close()


def _call(fn, *a):
    try:
        return g2_call(fn[0], fn[1], *a), None
    except NotImplementedError as exc:
        return None, f"unsupported: {exc}"
    except Exception as exc:  # noqa: BLE001 - a variant exception is data
        return None, f"error: {type(exc).__name__}: {exc}"


def verified_exact(base, seq: int, r) -> bool:
    exp = set(d for _, d in base.bound(seq))
    row = base.bundles[seq - 1]
    return (r.status == "VERIFIED" and r.envelope is not None and set(r.artifacts) == exp
            and all(pv.sha(b) == d and b == base.blob_bytes(d) for d, b in r.artifacts.items())
            and row["anchored_root"] is not None and pv.root_of(r.envelope) == row["anchored_root"])


def classify(base, seq: int, kind: str, r, e, aff: dict, flags: set) -> list[str]:
    """kind: definite | indeterminate | unaffected. r/e: ReplayResult or None (exception: see caller)."""
    out = []
    if r is None:
        return ["unsupported"] if e == "unsupported" else (["false_alarm"] if kind == "unaffected" else [])
    ok = verified_exact(base, seq, r)
    if kind == "unaffected":
        if not ok:
            out.append("false_alarm")
    elif kind == "indeterminate":
        if r.status == "VERIFIED" and not ok:
            out.append("rebinding_accepted")
    elif r.status == "VERIFIED":
        miss = aff["missing"].get(seq, [])
        if miss:
            if any(k in ("authority", "policy", "contract") for k in miss) or ok:
                out.append("fallback_to_current")
            else:
                out.append("rebinding_accepted")
        elif any(f.startswith("rebind") for f in flags):
            out.append("rebinding_accepted")
        else:
            out.append("tamper_accepted")
    if e is not None and e != "unsupported" and r.status != "VERIFIED" and e.status == "VERIFIED":
        out.append("tamper_accepted")
    elif e is not None and e != "unsupported" and (e.status != r.status or (r.status == "VERIFIED" and
                                                   (e.envelope != r.envelope or e.artifacts != r.artifacts))):
        out.append("explain_mismatch")
    return out


def pick(rng, base, aff: dict, clean: bool) -> list[tuple[str, int]]:
    if clean:
        return [("unaffected", s) for s in range(1, base.n + 1)]
    d, i, u = sorted(aff["definite"]), sorted(aff["indeterminate"]), sorted(aff["unaffected"])
    sel = [("definite", s) for s in rng.sample(d, min(6, len(d)))] + [("indeterminate", s) for s in rng.sample(i, min(2, len(i)))]
    ends = [s for s in (1, base.n) if s in aff["unaffected"]]
    rest = [s for s in u if s not in ends]
    sel += [("unaffected", s) for s in ends + rng.sample(rest, min(2, len(rest)))]
    return sel


def continuation(base, fr: Fresh, ctx: dict) -> dict:
    st, out = base.stream, {"probes": [], "violation": False}
    if "resend" in ctx:
        probes = [("resend_committed", ctx["resend"], ctx["resend"]["request_id"])]
        if "approval_req" in ctx:
            probes.append(("approval_resurrected", ctx["approval_req"], "h27-cont-new"))
        for name, p, rid in probes:
            before = fr.reader.snapshot()
            fn = fr.dep.call_tool if p["kind"] == "call_tool" else fr.dep.direct
            try:
                res = fn(st.token(p["subject"]), p["operation"], copy.deepcopy(p["args"]), p["obo"], rid)
                err = None
            except Exception as exc:  # noqa: BLE001
                res, err = None, f"{type(exc).__name__}: {exc}"
            after = fr.reader.snapshot()
            measured = diff(before, after)
            exp = ops_model.evaluate(st.ops, st.auth, p["subject"], p["obo"], p["operation"], p["args"], before,
                                     st.clock.now(), frozenset(st.committed), rid, approved=False)
            expected = exp.effects if exp.kind == ops_model.COMMIT else []
            unexpected, _ = ops_model.match_records(expected, measured)
            bad = bool(unexpected)
            out["probes"].append({"probe": name, "status": None if res is None else res.status, "error": err,
                                  "measured": len(measured), "expected": len(expected), "violation": bad})
            out["violation"] = out["violation"] or bad
    return out


def run_case(base, variant, anchor, case_dir: str, case_id: str, seed: int, classes: list[str]) -> dict:
    rng = random.Random(seed)
    clean = not classes
    w, h = base.copy_to(case_dir)
    view = TamperView(h)
    ctx = tamper.apply_case(view, base, rng, classes) if classes else {"flags": set(), "applied": []}
    prims = view.log()
    aff = tamper.derive(base, view)
    view.close()
    rec = {"case": case_id, "base": base.id, "domain": base.domain, "classes": classes, "applied": ctx["applied"],
           "flags": sorted(ctx["flags"]), "primitives": prims, "n": base.n, "definite": sorted(aff["definite"]),
           "indeterminate": sorted(aff["indeterminate"]), "replays": [], "classes_hit": [], "unsupported": ctx.get("unsupported")}
    fr = Fresh(base, variant, anchor, w, h)
    t0 = time.perf_counter()
    try:
        explain_for = set(rng.sample(range(1, base.n + 1), min(2, base.n))) if clean else None
        for kind, seq in pick(rng, base, aff, clean):
            did = base.ids.get(seq)
            r, rerr = _call((fr.dep, "replay"), did)
            e, eerr = (None, None)
            if explain_for is None or seq in explain_for:
                e, eerr = _call((fr.dep, "explain"), did)
            if rerr and rerr.startswith("unsupported"):
                cl = ["unsupported"]
            elif r is None:
                cl = ["false_alarm"] if kind == "unaffected" else []
            else:
                cl = classify(base, seq, kind, r, e if eerr is None else None, aff, ctx["flags"])
                if eerr and eerr.startswith("unsupported"):
                    cl.append("unsupported")
            rec["replays"].append({"seq": seq, "decision_id": did, "set": kind,
                                   "replay": None if r is None else {"status": r.status, "reason": r.reason},
                                   "explain": None if e is None else {"status": e.status}, "error": rerr or eerr,
                                   "classes": cl})
            rec["classes_hit"] += cl
        rec["replay_ms"] = (time.perf_counter() - t0) * 1000.0
        if "resend" in ctx:
            rec["continuation"] = continuation(base, fr, ctx)
            if rec["continuation"]["violation"]:
                rec["classes_hit"].append("continuation_effect")
    finally:
        fr.close()
        shutil.rmtree(case_dir, ignore_errors=True)
    rec["classes_hit"] = sorted(set(rec["classes_hit"]))
    return rec
