"""End of sequence judgement: outcome plane, recovery, world check, injection effectiveness (invalid_if a), boundary probes (s9)."""
from __future__ import annotations

from collections import defaultdict

from r3_oracle import continuity as C
from r3_oracle import recoverymodel as RM

from r3_shared.recovery import INPUT_INVALID_REASONS

from . import judge_ext as JE, judge_rec as JR, judge_wl, specs


def _fault_at(phi):
    def f(system, a, b):
        return any(w["node"] == f"EXT:{system}" and w["from_tick"] <= b and a < w["to_tick"] for w in phi.windows) or phi.mode("OBS", b) is not None
    return f


def _finish(R, row, ctx, ev, phi, versions, rep, state, systems, cw, base, dep, marks, tamper_t):
    window = systems["window"]
    dl = JE.dep_ledger(ctx.led, dep, base)
    intents, tick0 = state["intents"], state["tick0"]
    reads = defaultdict(list)
    for e in ev:
        if e["k"] == "reconcile" and e.get("rid"):
            reads[e["rid"]].append(e)
    fa = _fault_at(phi)
    oc = JE.eval_outcomes(reads, intents, tick0, dl, systems, window, fa)
    for r in oc["false"]:
        row["classes"].setdefault("false_reconciled_success", []).append(r)
    for r in oc["mis_outcome"]:
        row["mis"].setdefault("outcome-plane", []).append(r)
        row["classes"].setdefault("misclassified_dependency_failure", []).append({"kind": "outcome-plane", **r})
    row["outcome_other"] = len(oc["other"])
    for rid, i, n in JE.duplicates(dl, intents):
        row["classes"].setdefault("duplicate_effect", []).append({"rid": rid, "effect": i, "extra_rows": n})
    out = JE.outside_scope(dl, intents)
    if out:
        row["classes"].setdefault("effect_outside_scope", []).append({"ledger_seq": out[:10], "n": len(out)})
    byz = (R.get("seq_def") or {}).get("byz")
    row["outcome_progress"] = {"checked": 0, "lost": []}
    if not R.get("kills") and not byz:
        for rid, ints in intents.items():
            for I in ints:
                t0 = tick0[rid]
                if I["observability"] != "full" or any(fa(I["system"], t0, t0 + window + 1) for _ in (0,)):
                    continue
                k = (rid, I["effect_index"])
                if k not in oc["oracle"]:
                    continue
                row["outcome_progress"]["checked"] += 1
                if oc["got"].get(k) != "RECONCILED_SUCCESS":          # G5-E35 B2 / R29-12: a SAFE-window request counts only if its outcome ENDS RECONCILED_SUCCESS
                    row["outcome_progress"]["lost"].append({"rid": rid, "effect": I["effect_index"], "got": oc["got"].get(k), "oracle": oc["oracle"][k][0]})
    lost = {x["rid"] for x in row["outcome_progress"]["lost"]}
    for q in row["req"]:                      # G5-E35 B2: such a request does not count toward safe progress (overall / per class / per node)
        if q.get("rid") in lost and q.get("progressed") and q.get("k") == "request":
            q["progressed"] = False
            deps = set(C.decision_deps(ctx.graph, R["domain"], "request", q.get("op")))
            for node in q.get("phi") or []:
                if node not in deps and node in row["unrelated"]:
                    row["unrelated"][node][1] -= 1
    rec = JR.judge_recovery(R, ev, versions, intents, tick0, dl, systems, window, rep.open_approvals(), reads, fa, ctx.anchor_of(R))
    row["recovery"] = {"rc1": rec["rc1"], "rc2": rec["rc2"]}
    row["recovery_checks"] = [rec["checks"], rec["passes"]]
    for c, dd in rec["classes"].items():
        row["classes"].setdefault(c, []).extend(dd)
    row["restricted_io"] = list(rec["restricted_io"])
    for e in ev:
        if e["k"] == "rc1" and e.get("auth_refused_restricted"):      # G5-E25: bounded by transcript order (service sequence), not by tick
            row["restricted_io"].append({"resume": e["resume"], "what": "AuthorityService fetch refused during the restricted phase",
                                         "n": e["auth_refused_restricted"]})
    for e in ev:
        if e["k"] == "rc1" and e.get("ext_restricted"):                # G5-E25 (ii): ExternalWorld request inside the window (service seq order)
            row["restricted_io"].append({"resume": e["resume"], "what": "ExternalWorld request by the resumed deployment during the restricted phase",
                                         "n": e["ext_restricted"]})
        if e["k"] == "rc1" and e.get("obs_reads_restricted"):          # G5-E25 (iii): observer read inside the window (None = not instrumented)
            row["restricted_io"].append({"resume": e["resume"], "what": "observer read by the resumed deployment during the restricted phase",
                                         "n": e["obs_reads_restricted"]})
    row["obs_reads_instrumented"] = all(e.get("obs_reads_restricted") is not None for e in ev if e["k"] == "rc1")
    if not row["obs_reads_instrumented"]:
        row["harness"].append("observer_log_missing")                  # a G5 run without the observer read log is INVALID, never clean
    for item in row["restricted_io"]:                                  # G5-E25 / R29-10: every restricted_io item is a recovery_divergence
        row["classes"].setdefault("recovery_divergence", []).append({**item, "what": "restricted_io", "detail": item["what"]})
    w = R.get("world")
    if w is not None:
        act = {"objects": {k: {"props": v} for k, v in w["objects"].items()}, "links": w["links"]}
        if RM.world_digest(act) != RM.world_digest(rep.snap):
            d = {"predicted_digest": RM.world_digest(rep.snap)[:16], "actual_digest": RM.world_digest(act)[:16]}
            if rec["rc1"] or rec["rc2"]:
                row["classes"].setdefault("recovery_divergence", []).append({"what": "world_divergence", **d})
            else:
                row["harness"].append("world_divergence")
    judge_wl.check_marks(R, ctx, row, ev, dl, intents, oc)           # G5-E33 (a)-(c), after RC2
    judge_wl.check_wl(R, row)                                         # G5-E33 (d)
    row["world_digest"] = RM.world_digest(rep.snap)[:32]
    row["injection"] = _injection(R, ev, dl, phi)
    row["stale_sensitive"] = sum(1 for q in row["req"] if q.get("stale_sensitive"))


def _injection(R, ev, dl, phi) -> list:
    out = []
    a, an = R["auth"], R.get("anchor") or {}
    ext_rows = R.get("ext") or []
    for e in (x for x in ev if x["k"] == "fault_start"):
        node, f, to = e["node"], e["frm"], e["to"]
        enforced, refused = False, 0
        if node == "AUTH":
            enforced = any(w["from_tick"] == f and w["to_tick"] == to for w in a["faults"] if w["deployment"] == R["dep"])
            refused = sum(1 for r in a["refused"] if r["deployment"] == R["dep"] and f <= r["tick"] < to)
        elif node == "ANCHOR":
            enforced = any(w["from_tick"] == f and w["to_tick"] == to for w in an.get("windows", []))
            refused = sum(1 for r in an.get("log", []) if f <= r["tick"] < to)
        elif node.startswith("EXT:"):
            s = node[4:]
            enforced = any(r["system"] == s and r["from_tick"] == f and r["to_tick"] == to for r in ext_rows if r["deployment"] == R["dep"])
            refused = sum(1 for r in dl["audit"] if r["system"] == s and f <= r["tick"] < to and e["mode"] == "reply_lost" and r["outcome"] == "applied")
            refused += sum(1 for r in dl.get("unverified", []) if r["claim"].get("system") == s and f <= r["tick"] < to
                           and r["outcome"] == "refused" and r["reason"] == "unavailable")      # G5-E4: attributed by the cap's claim
        elif node == "OBS":
            enforced = any(w["from"] == f and w["to"] == to for w in R.get("obs_windows", []))
            refused = sum(1 for x in ev if x["k"] == "reconcile" and f <= x["t"] < to)
        out.append({"fid": e["fid"], "cls": e["cls"], "node": node, "mode": e["mode"], "from": f, "to": to, "issued": e["issued"],
                    "enforced": bool(e["issued"] and enforced), "refused_calls": refused})
    armed = [x for x in ev if x["k"] == "crash_armed"]
    missed = [h for h in R.get("harness", []) if h["row"] == "injection_miss" and "crash point" in str(h.get("why", ""))]
    for i, x in enumerate(armed):                                  # G5-E35 B7: fired = a host death NOT forced by the harness between this arming and the next
        nxt = armed[i + 1]["n"] if i + 1 < len(armed) else 10 ** 9
        deaths = [d for d in ev if d["k"] == "host_dead" and x["n"] < d["n"] < nxt and not d.get("forced")]
        out.append({"crash_point": x["point"], "key": x["key"], "fired": 1 if deaths else 0, "fired_tick": deaths[0]["kill"] if deaths else None,
                    "cp_missed_total": len(missed)})
    return out


def _boundary(R, ctx, row):
    b = (R.get("seq_def") or {}).get("boundary")
    row["boundary"] = {"probe": b, "explicit": True, "violations": []}
    v = row["boundary"]["violations"]
    ev, dom = R["events"], R["domain"]
    phi = build = None
    from .judge import build_phi, versions_of
    versions, phi = versions_of(R, ctx), build_phi(R)
    graph = ctx.graph
    sends = [{"kind": "request" if e["k"] in ("request", "redeliver") else e["k"], "op": e.get("operation"), "t": e["t"], "invalid_probe": bool(e.get("invalid_probe"))}      # G5-E28 (a): same source as judge.py
             for e in ev if e["k"] in ("request", "redeliver", "read", "approve") and e.get("err") != "no_host"]
    renew = C.renew_pair(sends, phi, graph, dom)
    if b in ("B1", "B2"):
        for e in (x for x in ev if x["k"] in ("request", "read") and x.get("err") != "no_host"):
            cls = C.classify({"kind": "request" if e["k"] == "request" else "read", "op": e.get("operation"), "t": e["t"], "rid": e.get("rid")}, phi, graph, dom, renew, versions)
            if cls.kind == C.SAFE:
                continue
            res = e.get("res") or {}
            body = res.get("body") or {}
            node = "AUTH" if b == "B1" else "ANCHOR"
            ok_reply = res.get("status") == "UNAVAILABLE" and body.get("reason") == "dependency_unavailable" and body.get("dependency") in cls.down
            probe_ok = bool(e.get("invalid_probe") and res.get("status") == "INVALID"
                            and ctx.reason_map.get(body.get("reason"), body.get("reason")) in INPUT_INVALID_REASONS)   # G5-E28 (b): any member
            ok_reply = ok_reply or probe_ok
            if e.get("invalid_probe"):
                row["boundary"].setdefault("probes", []).append({"shape": e.get("probe_shape"), "status": res.get("status") or e.get("err"),
                                                                 "reason": body.get("reason"), "ok": bool(ok_reply), "node": node,
                                                                 "t": e["t"]})
            ok_reply = ok_reply or (b == "B2" and res.get("status") == "UNKNOWN" and body.get("reason") == "in_doubt") or e.get("err") == "no_reply"
            if not ok_reply:
                v.append({"t": e["t"], "status": res.get("status") or e.get("err"), "body": body, "node": node})
        if b == "B2":
            t0 = min((x["t"] for x in ev if x["k"] == "fault_start" and x.get("node") == "ANCHOR"), default=None)
            for e in (x for x in ev if x["k"] == "request" and t0 is not None and x["t"] >= t0 and (x.get("res") or {}).get("status") == "OK"):
                v.append({"t": e["t"], "rid": e.get("rid"), "status": "OK", "node": "ANCHOR", "why": "OK governed result with the anchor permanently unreachable"})
            probes = [x for x in ev if x["k"] == "replay_probe"]
            for e in probes:
                if e.get("status") == "VERIFIED":
                    v.append({"t": e["t"], "rid": e["rid"], "status": "VERIFIED", "why": "replay VERIFIED with the anchor permanently unreachable"})
            if t0 is None or not probes:
                row["harness"].append("injection_miss")
    elif b == "B3":
        for e in (x for x in ev if x["k"] == "reconcile"):
            res = e.get("res") or {}
            for o in (res.get("body") or {}).get("outcomes", []) if res.get("status") == "OK" else []:
                if o.get("state") in ("RECONCILED_SUCCESS", "RECONCILED_FAILED", "DIVERGED") and phi.mode("OBS", e["t"]) is not None:
                    v.append({"t": e["t"], "rid": e["rid"], "state": o["state"]})
    elif b == "B4":
        tam = next((x for x in ev if x["k"] == "tamper"), None)
        csl = next((x for x in ev if x["k"] == "canonical_state_lost"), None)
        if tam is not None and csl is None:
            for e in (x for x in ev if x["k"] in ("request", "redeliver") and x["t"] >= tam["t"] and x.get("err") != "no_host"):
                res = e.get("res") or {}
                if not (res.get("status") == "UNAVAILABLE" and (res.get("body") or {}).get("reason") == "state_lost") and e.get("err") != "no_reply":
                    v.append({"t": e["t"], "rid": e.get("rid"), "status": res.get("status") or e.get("err"), "why": "accepted after canonical history loss"})
        if tam is None:
            row["harness"].append("injection_miss")
        w = R.get("world") or {}
        dup = defaultdict(int)
        for m in w.get("marks", []):
            dup[m["data"].get("request_id")] += 1
        v += [{"rid": r, "why": "request_id committed twice after history loss"} for r, n in dup.items() if n > 1 and r]
    row["boundary"]["explicit"] = not v
    if v:
        row["classes"].setdefault("boundary_not_explicit", []).extend(v)
    return row
