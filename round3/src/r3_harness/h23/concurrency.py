"""A8 concurrency driver (PROT-H23-A8 R10): Python threads against ONE Deployment, judged by the serial-order oracle.

Scenario types (cycled by index, deterministic per (seed, i)):
  same      k in {2,4,8} threads send the SAME request (same request_id) -> the oracle's effects exactly once
  contend   2-4 DIFFERENT requests that conflict on state (the oracle's serial orders disagree) -> the final world must
            equal the oracle's final world for SOME serial order (all <= 24 orders enumerated)
  approval  2 identical requests (different ids) racing for ONE pre-approval -> at most one commits
  free      2-4 non-conflicting legitimate requests -> all must commit (a refusal is concurrent_progress_loss)
Ground truth is the final world snapshot (the meter's reader); CallResult is used for nothing except labelling a
refusal in the record. Classes: concurrency_unserializable (safety), concurrent_progress_loss (progress, reported).
"""
from __future__ import annotations

import copy
import itertools
import random
import threading

from r3_oracle import ops_model, serial

from . import approval_rules
from .chooser import RandChooser
from .corpus import DOMAINS, new_env
from .goodargs import pick_args

TYPES = ("same", "contend", "approval", "free")
KS = (2, 4, 8)
JOIN_S = 60.0


_POOLS: dict[str, dict] = {}  # per domain: harness-side only, derived from the (variant-independent) seed world


def _pool(env) -> dict:
    """Well-formed authorised requests (committing now, or refused only by state) for the seed world, plus the pairs whose serial orders disagree (the order in which they run matters)."""
    if env.domain in _POOLS:
        return _POOLS[env.domain]
    ch = RandChooser(random.Random(f"a8-pool-{env.domain}"))
    ops, snap, cands, seen = {o["name"]: o for o in env.ops["operations"]}, env.snapshot(), [], set()
    for a in env.agents():
        for name in env.authorized_ops(a):
            op = ops[name]
            base = pick_args(env, op, ch, a, "commit")
            rins = [i for i in op["inputs"] if i["type"] == "resource"]
            axes = [[k.split(":", 1)[1] for k in snap["objects"] if k.startswith(i["resource_type"] + ":")]
                    for i in rins]
            combos = list(itertools.product(*axes)) or [()]
            for combo in ch.rng.sample(combos, min(len(combos), 40)):
                args = dict(base, **{i["name"]: v for i, v in zip(rins, combo)})
                o = ops_model.evaluate(env.ops, env.auth, a, None, name, args, snap, env.clock.now())
                order_dependent = o.kind == ops_model.DENIED_RULE or (
                    o.kind == ops_model.INVALID and o.detail.startswith("precondition"))
                key = repr((a, name, sorted(args.items(), key=str)))
                if (o.commits or order_dependent) and not o.used_approval and key not in seen:
                    seen.add(key)
                    cands.append({"subject": a, "obo": None, "op": name, "args": args, "now": bool(o.commits)})
    cands = ch.rng.sample(cands, min(len(cands), 70))
    pairs = []
    for x in range(len(cands)):
        for y in range(x + 1, len(cands)):
            grp = [dict(cands[x], rid="p0"), dict(cands[y], rid="p1")]
            if len(serial.distinct_finals(env.ops, env.auth, snap, env.clock.now(), grp)) > 1:
                pairs.append((x, y))
    appr = []
    for req in env.agents():
        for op in approval_rules._approval_ops(env):
            args = next((x for x in (approval_rules._needs_args(env, ch, req, op) for _ in range(4)) if x), None)
            apv = approval_rules._approver(env, req, op["name"], args, valid=True) if args else None
            if apv and op["name"] in env.authorized_ops(req):
                appr.append({"requester": req, "approver": apv, "op": op["name"], "args": args})
    _POOLS[env.domain] = {"cands": cands, "pairs": pairs, "approvals": appr}
    return _POOLS[env.domain]


def _rids(env, grp):
    for j, q in enumerate(grp):
        q["rid"] = f"cc-{env.tag}-{j}"
    return grp


def _state_group(env, ch, pool, conflict: bool, size: int):
    cands, snap = pool["cands"], env.snapshot()
    if conflict:
        if not pool["pairs"]:
            return None
        x, y = ch.choice(pool["pairs"])
        grp = [dict(cands[x]), dict(cands[y])] + [dict(ch.choice(cands)) for _ in range(size - 2)]
        return _rids(env, grp)
    for _ in range(40):
        live = [c for c in cands if c["now"]]
        grp = _rids(env, [dict(ch.choice(live)) for _ in range(size)]) if live else []
        if grp and len(serial.distinct_finals(env.ops, env.auth, snap, env.clock.now(), grp)) == 1 and all(
                k == ops_model.COMMIT for k in serial.simulate(env.ops, env.auth, snap, env.clock.now(), grp,
                                                               range(size))[1]):
            return grp
    return None


def _approval_group(env, ch, pool):
    if not pool["approvals"]:
        return None
    a = ch.choice(pool["approvals"])
    rec = env.approve(rule="conc_approval:approve", token=env.token(a["approver"]), approver=a["approver"],
                      requester=a["requester"], operation=a["op"], args=copy.deepcopy(a["args"]), tags={"approval"})
    if "forbidden_effect" in rec["classes"] or not env.approvals:
        return None
    grp = _rids(env, [{"subject": a["requester"], "obo": None, "op": a["op"], "args": a["args"]} for _ in range(2)])
    return grp, dict(env.approvals)


def _fire(env, reqs: list[dict]) -> list[dict]:
    bar, out = threading.Barrier(len(reqs)), [None] * len(reqs)

    def work(i):
        q = reqs[i]
        fn = env.dep.call_tool if q["via"] == "call_tool" else env.dep.direct
        try:
            bar.wait(timeout=JOIN_S)
            r = fn(env.token(q["subject"]), q["op"], copy.deepcopy(q["args"]), q.get("obo"), q["rid"])
            out[i] = {"status": r.status}
        except Exception as exc:  # noqa: BLE001
            out[i] = {"status": "EXCEPTION", "error": f"{type(exc).__name__}: {exc}"}

    for q in reqs:
        q["via"] = "call_tool" if q["op"] in env.tools(q["subject"]) else "direct"
        env.token(q["subject"])
    ts = [threading.Thread(target=work, args=(i,), daemon=True) for i in range(len(reqs))]
    [t.start() for t in ts]
    [t.join(JOIN_S) for t in ts]
    return [o or {"status": "HUNG"} for o in out]


def scenario(variant, specs, seed: int, i: int, types=TYPES) -> dict:
    stype, domain = types[i % len(types)], DOMAINS[(i // len(types)) % len(DOMAINS)]
    env = new_env(variant, domain, specs, f"cc{seed}-{i}")
    try:
        ch = RandChooser(random.Random(seed * 104_729 + i))
        rec = {"scenario": i, "type": stype, "domain": domain, "classes": [], "skipped": None, "requests": []}
        budget, pool, kind = None, _pool(env), None
        k = KS[(i // len(types)) % 3] if stype == "same" else ch.randint(2, 4)
        reqs = None
        if stype == "same":
            g = _state_group(env, ch, pool, False, 1)
            reqs = _rids(env, [dict(g[0]) for _ in range(k)]) if g else None
            for q in reqs or []:
                q["rid"] = "cc-same"
        elif stype == "contend":
            reqs, kind = _state_group(env, ch, pool, True, k), "state"
        if stype == "approval" or (stype == "contend" and not reqs):
            got = _approval_group(env, ch, pool)
            reqs, budget = got if got else (None, None)
            kind = "approval" if reqs else kind
            if not reqs and stype == "approval":  # domain without approvals: contend on state instead
                reqs, kind = _state_group(env, ch, pool, True, k), "state"
        elif stype == "free":
            reqs = _state_group(env, ch, pool, False, k)
        rec["contention"] = kind
        if not reqs:
            rec["skipped"] = "no suitable request group found"
            return rec
        rec["k"] = len(reqs)
        snap0 = env.snapshot()
        res = _fire(env, reqs)
        final = env.snapshot()
        uniq, idx = [], []
        for q in reqs:  # identical requests (same scenario) are one request for the serial search
            sig = (q["subject"], q["op"], repr(q["args"]), q["rid"])
            if sig not in [u[0] for u in uniq]:
                uniq.append((sig, q))
            idx.append([u[0] for u in uniq].index(sig))
        judged = [u[1] for u in uniq]
        j = serial.judge(env.ops, env.auth, snap0, env.clock.now(), judged, final, budget)
        conflict = len(serial.distinct_finals(env.ops, env.auth, snap0, env.clock.now(), judged, budget)) > 1
        refused = [x for x in range(len(reqs)) if idx[x] not in j["subset"]] if j["match"] == "subset" else []
        acked_absent = [x for x in refused if res[x]["status"] == "OK"]  # told "committed", not in any serial order
        if j["match"] is None or acked_absent:
            rec["classes"].append("concurrency_unserializable")
        elif refused:
            rec["classes"].append("concurrent_progress_loss")
        rec.update({"match": j["match"], "order": j["order"], "subset": j["subset"], "conflicting": conflict,
                    "losses": len(refused), "serial_orders_tried": j["serial_orders_tried"],
                    "requests": [{"subject": q["subject"], "op": q["op"], "args": q["args"], "rid": q["rid"],
                                  "status": r["status"]} for q, r in zip(reqs, res)]})
        return rec
    finally:
        env.close()


def summarise(rows: list[dict]) -> dict:
    """Recomputed by the evaluator from the raw rows; never trusted from a summary."""
    done = [r for r in rows if not r.get("skipped")]
    types, ks = {}, {}
    for r in done:
        types[r["type"]] = types.get(r["type"], 0) + 1
        if r["type"] == "same":
            ks[str(r["k"])] = ks.get(str(r["k"]), 0) + 1
    cnt = {c: sum(c in r["classes"] for r in done) for c in ("concurrency_unserializable", "concurrent_progress_loss")}
    return {"scenarios": len(rows), "executed": len(done), "skipped": len(rows) - len(done), "by_type": types,
            "same_k": ks, "conflicting": sum(bool(r.get("conflicting")) for r in done),
            "domains": sorted({r["domain"] for r in done}), "losses": sum(r.get("losses", 0) for r in done),
            "serial_orders_tried_max": max((r.get("serial_orders_tried", 0) for r in done), default=0), **cnt}


def run(variant, specs, n: int, seed: int, types=TYPES):
    for i in range(n):
        yield scenario(variant, specs, seed, i, types)
