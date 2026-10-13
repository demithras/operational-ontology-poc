"""Classification of one sequence (one row per (sequence, variant)) from RAW records, the closed ledger, the anchor log and the
AuthorityService log, using only the ORACLE (r3_oracle.continuity / recoverymodel / extoracle / ops_model / disclosure). Variant CallResults
are used for exactly what the protocol makes legitimate: the reply STATUS/BODY (compared with the oracle class and admissible set), the
returned outcome records and recovery views (compared with the oracle prediction). Total and deterministic; never raises on a malformed record."""
from __future__ import annotations

import json
from collections import defaultdict

from r3_oracle import approvals, extoracle, ops_model
from r3_oracle import continuity as C
from r3_oracle import recoverymodel as RM
from r3_oracle.disclosure import low_view
from r3_oracle.disclosure_reads import expected_list_objects, expected_read_object

from . import faults, judge_ext as JE, judge_rec as JR, specs

CLASSES = ("forbidden_effect", "stale_authority_commit", "stale_authority_after_restart", "effect_outside_scope", "disclosure_leak",
           "unanchored_ack", "tampered_record_trusted", "false_success", "false_reconciled_success", "duplicate_effect", "duplicate_commit",
           "misclassified_dependency_failure", "recovery_nondeterministic", "recovery_divergence", "boundary_not_explicit")
BLOCKING = ("unsupported", "host_spawn_failure", "harness_exception", "generator_redraw_exhausted", "service_log_unavailable", "observer_log_missing", "anchor_head_unreadable", "world_log_unobserved")
HARNESS = BLOCKING + ("injection_miss", "call_timeout", "world_lock_timeout", "redeliver_unknown_rid", "tamper_host_alive", "stride_exceeded")
MIS_KINDS = ("OK", "DENIED", "INVALID", "UNAVAILABLE", "UNKNOWN", "outcome-plane")
REQ_KINDS = ("request", "redeliver")


class Ctx:
    """Run-wide judge context: the closed ledger index, the anchor log index, the frozen specs."""

    def __init__(self, led, anchor_entries, reason_map: dict | None = None, anchor_seq: dict | None = None, workers: int = 1):
        """anchor_entries / anchor_seq: {worker i: set of (stream, decision_id)} / {worker i: {(stream, decision_id): [seq]}} (G5-E30 (e): one
        anchor per worker; a sequence is judged against the anchor of the worker that ran it, worker = j % workers). A plain set / dict is
        taken as the single anchor of every sequence (unit tests)."""
        self.led, self.reason_map, self.workers = led, reason_map or {}, max(1, workers)
        self.anchor, self.anchor_seq = anchor_entries, anchor_seq or {}
        self.graph = specs.graph()
        self.docs = {d: {C_digest: doc for C_digest, doc in ((_digest(x), x) for x in specs.family(d))} for d in specs.DOMAINS}


    def _pick(self, store, R, empty):
        if isinstance(store, dict) and all(isinstance(k, int) for k in store) and store:
            return store.get((R.get("j") or 0) % self.workers, empty)
        return store if store is not None else empty

    def anchor_of(self, R: dict) -> set:
        return self._pick(self.anchor, R, set())

    def anchor_seq_of(self, R: dict) -> dict:
        return self._pick(self.anchor_seq, R, {})


def _digest(doc):
    from .gen_model import digest_of
    return digest_of(doc)


def _blank(R: dict) -> dict:
    return {"seq": R["seq"], "j": R.get("j"), "stratum": R.get("stratum"), "domain": R.get("domain"), "classes": {}, "harness": [], "req": [],
            "mis": {}, "unrelated": {}, "recovery": None, "injection": [], "boundary": None, "stale_sensitive": 0, "planned_classes": [],
            "outcome_other": 0, "recovery_checks": [0, 0], "restricted_io": []}


def _hit(row, cls, detail):
    row["classes"].setdefault(cls, []).append(detail)


def judge_seq(R: dict, ctx: Ctx) -> dict:
    row = _blank(R)
    sd = R.get("seq_def") or {}
    row["planned_classes"] = sd.get("classes", [])
    for h in R.get("harness", []):
        row["harness"].append(h["row"])
    if R.get("unsupported"):
        row["harness"].append("unsupported")
    csl = any(e["k"] == "canonical_state_lost" for e in R.get("events", []))
    if R.get("deploy_error") and not csl and "unsupported" not in row["harness"] and "host_spawn_failure" not in row["harness"]:
        row["harness"].append("host_spawn_failure")
    if any(h in BLOCKING for h in row["harness"]) or R.get("auth") is None:
        return row
    try:
        if R["stratum"] == "bnd":
            return _boundary(R, ctx, row)
        return _judge(R, ctx, row)
    except Exception as exc:  # noqa: BLE001 - an oracle/judge bug is a visible harness row, never a silent pass
        row["harness"].append("harness_exception")
        row["judge_error"] = f"{type(exc).__name__}: {exc}"[:300]
        return row


def build_phi(R: dict) -> C.Phi:
    dep = R["dep"]
    ext_w = [{"target": x["system"], "mode": x["mode"], "from_tick": x["from_tick"], "to_tick": x["to_tick"], "deployment": x["deployment"]}
             for x in (R.get("ext") or []) if x["deployment"] == dep]
    obs_w = [{"from_tick": w["from"], "to_tick": w["to"]} for w in R.get("obs_windows", [])]
    obs_w += [{"from_tick": e["resume"], "to_tick": e["resume"] + 1} for e in R["events"] if e["k"] == "rc1"]
    auth_f = [f for f in R["auth"]["faults"] if f["deployment"] == dep]
    return C.phi_from_logs(auth_f, (R.get("anchor") or {}).get("windows", []), ext_w, obs_w,
                           [(k["kill"], k["resume"]) for k in R.get("kills", [])])


def versions_of(R: dict, ctx: Ctx) -> list:
    docs = ctx.docs[R["domain"]]
    return [{**v, "doc": docs.get(v["digest"])} for v in R["auth"]["versions"]]


def class_windows(R: dict) -> dict:
    """Fault-class activity windows for the progress ratios (i): service windows of F2/F3/F5 (actual), planned windows of F4/F6/F7,
    F1 = kill .. RC2, F8 = tamper .. RC2."""
    w = defaultdict(list)
    for f in R.get("faults", {}).values():
        w[f["cls"]].append([f["from"], f["to"]])
    for c, ws in (R.get("seq_def") or {}).get("class_windows", {}).items():
        if c in ("F4", "F6", "F7"):
            w[c] += ws
    rc2 = next((e["t_probe"] for e in reversed(R["events"]) if e["k"] == "rc2"), R.get("end_tick", 0))
    for k in R.get("kills", []):
        w["F1"].append([k["kill"], max(rc2, k["resume"] or 0)])
    tm = next((e["t"] for e in R["events"] if e["k"] == "tamper"), None)
    if tm is not None:
        w["F8"].append([tm, rc2])
    return dict(w)


def active(cw: dict, t: int) -> list:
    return sorted(c for c, ws in cw.items() if any(a <= t < b for a, b in ws))


def _judge(R: dict, ctx: Ctx, row: dict) -> dict:
    dom, base, dep, graph = R["domain"], R["base"], R["dep"], ctx.graph
    ops, _, systems = specs.load(dom)
    versions = versions_of(R, ctx)
    phi, ev = build_phi(R), R["events"]
    cw = class_windows(R)
    seed = specs.seed_snapshot(ops)
    for o in seed["objects"].values():
        pass
    for k, o in seed["objects"].items():
        if k.startswith("EvidenceSnapshot:"):
            o["props"]["snapshotObservedAt"] = base
    rep = RM.Replayer(ops, seed)
    marks = sorted(R["world"]["marks"], key=lambda m: m["seq"]) if R.get("world") else []
    by_rid = defaultdict(list)
    for m in marks:
        by_rid[m["data"].get("request_id")].append(m)
    sends = [{"kind": "request" if e["k"] in REQ_KINDS else e["k"], "op": e.get("operation"), "t": e["t"], "invalid_probe": e.get("invalid_probe", False)}
             for e in ev if e["k"] in REQ_KINDS + ("read", "approve") and e.get("err") != "no_host"]
    renew = C.renew_pair(sends, phi, graph, dom)             # G5-E28 (c): obligation list + .adm admissibility window
    crashed = {e["rid"] for e in ev if e["k"] in REQ_KINDS and e.get("err") == "no_reply"}
    keys = {e["key"] for e in ev if e["k"] == "crash_armed"}          # G5-E30 (b): the armed step comes from the corpus, never from a reply
    armed = {e["rid"] for e in ev if e["k"] in REQ_KINDS and e.get("rid") and (e["rid"] in keys or corr(e["rid"], 0) in keys)}
    tamper_t = next((e["t"] for e in ev if e["k"] == "tamper"), None)
    A = lambda t: C.authority_in_force(versions, t)            # noqa: E731
    doc_at = lambda t: C.doc_of(versions, A(t)) or versions[0]["doc"]  # noqa: E731
    state = {"armed": armed, "proc": set(), "committed": set(), "intents": {}, "tick0": {}, "decs": {}}
    seen_rids = {e["rid"] for e in ev if e["k"] in REQ_KINDS and e.get("rid")}

    def mark_cls(cls, detail, t):
        _hit(row, "tampered_record_trusted" if (tamper_t is not None and t >= tamper_t and cls in
                                                  ("forbidden_effect", "duplicate_commit", "stale_authority_commit")) else cls, detail)

    def process_marks(e):
        for m in by_rid.get(e["rid"], []):
            if m["seq"] in state["proc"]:
                continue
            state["proc"].add(m["seq"])
            t = m["tick"]
            if e["rid"] in state["committed"]:
                mark_cls("duplicate_commit", {"rid": e["rid"], "world_seq": m["seq"]}, t)
                continue
            dec, akey = rep.decide(doc_at(t), e["principal"], None, e["operation"], e["args"], base + t, None)
            if dec.kind != "OK":
                mark_cls("forbidden_effect", {"rid": e["rid"], "world_seq": m["seq"], "oracle": dec.reason}, t)
            if m["data"].get("authority_version") != A(t):             # R29-1: independent of the oracle decision ("even if the oracle would also allow it")
                mark_cls("stale_authority_commit", {"rid": e["rid"], "world_seq": m["seq"], "bound": m["data"].get("authority_version"), "in_force": A(t)}, t)
            if dec.kind == "OK":
                rep.commit(dec, akey, e["rid"])
                ints = extoracle.intended(systems, dec, e["rid"])
                if ints:
                    state["intents"][e["rid"]], state["tick0"][e["rid"]] = ints, t
            state["committed"].add(e["rid"])
            return m
        return None

    for e in ev:
        k = e["k"]
        if k == "approve":
            ok, _ = approvals.validate(ops, doc_at(e["t"]), e["approver"], e["requester"], e["operation"], e["args"])
            res = e.get("res")
            if ok and res and res["status"] == "OK" and not phi.down(e["t"], ("AUTH", "ANCHOR")):
                rep.approve(doc_at(e["t"]), e["approver"], e["requester"], None, e["operation"], e["args"])
        elif k in REQ_KINDS and e.get("rid") is not None:
            _request(R, row, e, ctx, phi, versions, renew, crashed, rep, state, process_marks, cw, base, ops, graph, dom, doc_at)
        elif k in ("delegate", "revoke") and e.get("res") and e["res"]["status"] == "OK":
            row["classes"].setdefault("false_success", []).append({"rid": e["rid"], "t": e["t"], "why": f"{k} probe answered OK (malformed / unknown edge)"})
        elif k == "read":
            _read(R, row, e, phi, graph, dom, renew, versions, rep, doc_at, ops, cw)
    for rid, ms in by_rid.items():                              # commits of requests nobody sent: foreign effects
        for m in ms:
            if m["seq"] not in state["proc"] and rid is not None and rid not in seen_rids:
                mark_cls("forbidden_effect", {"rid": rid, "world_seq": m["seq"], "why": "commit for a request the harness never sent"}, m["tick"])
    _finish(R, row, ctx, ev, phi, versions, rep, state, systems, cw, base, dep, marks, tamper_t)
    return row


from .gen_emit import corr  # noqa: E402
from .judge_req import _request, _read  # noqa: E402  (split for size)
from .judge_fin import _boundary, _finish  # noqa: E402
