"""Seam conformance C28-1..C28-6 (ORACLE-AND-HARNESS-G4 s9), runnable against ANY variant factory (registered variants and fakes).
Each check returns a list of problems (empty = conforms). An unbuilt seam is a problem (unsupported rows), never a skip."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from r3_oracle import extoracle
from r3_shared import extcap
from r3_shared.extadapter import FormError, validate_request
from r3_shared.extworld import start_external

from . import finalize, runner, specs, worlds
from .caserun import RunCtx, run_case
from .gen_case import build_case
from .gen_params import draw_params
from .judge import LedgerIndex, eval_outcomes


class World:
    """A private ExternalWorld + RunCtx for one conformance check."""
    def __init__(self, factory, vname="conf"):
        self.d = Path(tempfile.mkdtemp(prefix="h28c"))
        self.pair = worlds.Pair(self.d, "r3c")
        self.proc, self.ctl, self.sysseed = self.pair.main, self.pair.ctl, self.pair.sysseed
        self.ctx = RunCtx(self.ctl, str(self.d / "ext"), "conf", vname, tempfile.mkdtemp(prefix="h28c-w-", dir=str(self.d)))
        self.pair.attach(self.ctx)                  # G4-E26: twins run in their own world on the identical clock
        self.variant, self.recs, self.cases = factory(()), [], {}

    def run(self, case, kind="byz"):
        r = run_case(self.ctx, self.variant, case, kind)
        self.recs.append(r)
        return r

    closed = None

    def close(self):
        if self.closed is None:                 # idempotent: every check closes its ExternalWorld exactly once (no leaked processes)
            self.closed = self.pair.close()["external"]
        return self.closed

    def ledger(self) -> dict:
        return finalize.merged_ledger(self.d / "ext", self.d / worlds.TWIN_DIR)[0]

    def judge_inputs(self):
        led = LedgerIndex(self.ledger())
        return led


def _cases(seed, n, pred=None, kind="byz", start=0):
    ps, _ = draw_params(seed, max(n * 40, 60), kind, start)
    st, out = {}, []
    for p in ps:
        if len(out) >= n:
            break
        if pred and not pred(p):
            continue
        c = build_case(p, seed, st)
        if c is not None:
            out.append(c)
    return out


def _unsupported(recs) -> list[str]:
    return sorted({e for r in recs for e in r["errors"] if "unsupported" in e or "not implemented" in e}) + \
           [f"deploy error: {r['deploy_error']}" for r in recs if r["deploy_error"]]


def c1_seam(factory, n=12, seed=2811) -> list[str]:
    """With `external` given, 0 rows in the world external_effects table and the adapter submits the schedule implies (recorder); the
    legacy path (external=None) still writes its in-transaction rows."""
    w = World(factory)
    try:
        for c in _cases(seed, n, lambda p: p["system"] != "GEN-NULL" and not p["denied"] and not p["crash"]):
            w.run(c)
        bad = _unsupported(w.recs)
        if bad:
            return bad
        bad += [f"{r['case']}: world external_effects rows = {r['world_external_rows']} (must be 0 when `external` is given)"
                for r in w.recs if r["world_external_rows"]]
        sub = [r for r in w.recs if any(q["intents"] for q in r["requests"])]
        bad += [f"{r['case']}: committed external effect but the adapter received no submit" for r in sub
                if not any(r["recorder"].values()) and not any(a for a in r["attempts"])]
        return bad
    finally:
        w.close()


def c2_outcomes(factory, n_points=2000, seed=2811) -> list[str]:
    """Outcome function vs oracle over scripted ledgers: every rule N,U,D1,D2,D3,S,F,W (coverage set-difference), state+confidence+evidence equal."""
    from .conformance_scripts import scenario_cases
    w = World(factory)
    try:
        cases = scenario_cases(seed)
        recs, i = [], 0
        while sum(len(r["recon"]) for r in recs) < n_points and i < 4 * n_points:
            c = dict(cases[i % len(cases)], id=f"byz-{i:06d}", idx=i)
            c["requests"] = [dict(q, rid=f"h28-conf-{i:06d}-{q['i']}") for q in c["requests"]]
            recs.append(w.run(c))
            i += 1
            if _unsupported(recs):
                return _unsupported(recs)
        w.close()
        led = w.judge_inputs()
        bad, rules, pts = [], set(), 0
        for r in recs:
            ob = eval_outcomes(r, led, specs.load(r["domain"])[2])
            rules |= set(ob["rules"])
            pts += ob["points"]
            bad += [f"{r['case']}: {m}" for m in ob["mismatch"] + ob["false"]] + [f"{r['case']}: evidence {m}" for m in ob["evidence_bad"]]
        missing = {"N", "U", "D1", "D2", "D3", "S", "F", "W"} - rules
        return bad[:20] + ([f"rules not covered: {sorted(missing)}"] if missing else []) + ([f"only {pts} points"] if pts < n_points else [])
    finally:
        w.close()


def c3_caveats(factory, n=40, seed=2811) -> list[str]:
    w = World(factory)
    try:
        for c in _cases(seed, n, lambda p: p["system"] != "GEN-NULL" and not p["denied"]):
            w.run(c, "twin")
        bad = _unsupported(w.recs)
        if bad:
            return bad
        seen = 0
        for r in w.recs:
            ints = {(i["request_id"], i["effect_index"]): (i, q["tick"]) for q in r["requests"] for i in q["intents"]}
            for log in r["recorder"].values():
                for e in log:
                    seen += 1
                    try:
                        validate_request({k: e[k] for k in ("request_id", "effect_index", "system", "operation", "target", "payload",
                                                              "envelope_text", "cap")}, strict_cap=True)
                    except FormError as exc:
                        bad.append(f"{r['case']}: {exc}")
                        continue
                    key = (e["request_id"], e["effect_index"])
                    if key not in ints:
                        bad.append(f"{r['case']}: submit for no oracle-committed intent {key}")
                        continue
                    exp = extoracle.caveat_expectation(ints[key][0], ints[key][1], r["window"])
                    cav: dict = {}
                    for n_, v in extcap.caveats_of(e["cap"])[2:]:
                        cav.setdefault(n_, set()).add(v)
                    for k in ("system", "operation", "target", "payload_digest", "correlation", "not_after_tick"):
                        if cav.get(k) != {exp[k]}:
                            bad.append(f"{r['case']}: caveat {k} = {cav.get(k)} expected {exp[k]}")
                    if not (cav.get("max_uses") and max(cav["max_uses"]) in exp["max_uses_allowed"]):
                        bad.append(f"{r['case']}: max_uses {cav.get('max_uses')} not in {exp['max_uses_allowed']}")
        return bad[:20] + ([] if seen else ["no adapter submit observed"])
    finally:
        w.close()


def c4_decide_before_dispatch(factory, per_prim=300, seed=2811) -> list[str]:
    w = World(factory)
    try:
        cs = []
        for prim in ("G1", "G2", "L1", "L2"):
            cs += _cases(seed, per_prim, lambda p, q=prim: p.get("main") == q and not p["crash"])
        for c in cs:
            w.run(c, "byz")
            w.run(c, "twin")
        bad = _unsupported(w.recs)
        if bad:
            return bad
        from .judge import twin_diff
        by = {}
        for r in w.recs:
            by.setdefault(r["case"], {})[r["kind"]] = r
        return [f"{cid}: decision plane differs from honest twin: {twin_diff(k['byz'], k['twin'])}" for cid, k in by.items()
                if twin_diff(k["byz"], k["twin"])][:20]
    finally:
        w.close()


def c5_refusal_order(factory, n=30, seed=2811) -> list[str]:
    """Every adapter write attempt of a corpus run: the ExternalWorld receipt equals the oracle's refusal-order model."""
    w = World(factory)
    try:
        for c in _cases(seed, n, lambda p: p["system"] != "GEN-NULL"):
            w.run(c)
        bad = _unsupported(w.recs)
        if bad:
            return bad
        closed = w.close()
        key, systems = bytes.fromhex(closed["root_key_hex"]), specs.combined_systems()
        led = w.ledger()
        issued = {(r["nonce"], r["system"], r["deployment"]) for r in led["issued"]}
        used: dict = {}
        for r in w.recs:
            for a in r["attempts"]:
                cid = a["cap_chain"]
                pr = _predict_from_digest(key, systems, a["cap"], a, used.get(cid, 0), issued)
                if (pr == "applied") != (a["status"] == "applied") or (a["status"] == "refused" and a["reason"] != pr):
                    bad.append(f"attempt {a['kind']} {a['request_id']}: oracle {pr}, ExternalWorld {a['status']}/{a['reason']}")
                if a["status"] == "applied":
                    used[cid] = used.get(cid, 0) + 1
        return bad[:20]
    finally:
        w.close()


def _predict_from_digest(root_key, systems, cap, a, used, issued) -> str:
    """predict_write needs the payload; the attempt log keeps its digest, so evaluate the digest caveat directly (same order)."""
    from r3_shared.extadapter import payload_digest  # noqa: F401
    try:
        cav = extcap.verify(root_key, cap)
    except extcap.CapError:
        return "bad_signature"
    dep, system = cav[1][1], cav[0][1]
    if (extcap.root_nonce(cap), system, dep) not in issued:
        return "unknown_root"
    vals = lambda n: [v for k, v in cav if k == n]  # noqa: E731
    sysd = systems["systems"].get(system)
    if sysd is None or any(v != system for v in vals("system")):
        return "system_mismatch"
    if a["op"] not in sysd["operations"] or any(v != a["op"] for v in vals("operation")):
        return "operation_mismatch"
    if any(v != a["target"] for v in vals("target")):
        return "target_mismatch"
    if any(v != a["payload_digest"] for v in vals("payload_digest")):
        return "payload_mismatch"
    if len(set(vals("correlation"))) != 1:
        return "correlation_missing"
    if any(a["tick"] > v for v in vals("not_after_tick")):
        return "expired"
    if vals("max_uses") and used >= min(vals("max_uses")):
        return "uses_exhausted"
    return "applied"


def c6_crash_redelivery(factory, n=20, seed=2811) -> list[str]:
    """Crash after commit: restart + dispatch resubmits with the SAME chain id (<= 1 applied row for at_most_once)."""
    w = World(factory)
    try:
        for c in _cases(seed, n, lambda p: p["crash"] and p["system"] != "GEN-NULL" and not p["denied"]):
            w.run(dict(c, prims=["L3"]), "byz")          # a reply that forces re-submission after the crash
        bad = _unsupported(w.recs)
        if bad:
            return bad
        w.close()
        led = LedgerIndex(w.ledger())
        for r in w.recs:
            chains: dict = {}
            for log in r["recorder"].values():
                for e in log:
                    chains.setdefault((e["request_id"], e["effect_index"]), set()).add(extcap.chain_id(e["cap"]))
            bad += [f"{r['case']}: {k} resubmitted with {len(v)} different caps" for k, v in chains.items() if len(v) > 1]
            for q in r["requests"]:
                for i in q["intents"]:
                    if i["idempotency"] != "idempotent_set" and sum(1 for x in led.eff.get(r["dep"], []) if extoracle.key5(x) == extoracle.key5(i)) > 1:
                        bad.append(f"{r['case']}: more than one applied row for {i['correlation']}")
        return bad[:20]
    finally:
        w.close()


def c0_oracle_isolation() -> list[str]:
    from .evaluator import oracle_isolation
    return oracle_isolation()[1]


ALL = {"C28-1": c1_seam, "C28-2": c2_outcomes, "C28-3": c3_caveats, "C28-4": c4_decide_before_dispatch, "C28-5": c5_refusal_order,
       "C28-6": c6_crash_redelivery}
