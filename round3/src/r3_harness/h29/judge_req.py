"""Per-request / per-read judgement of the H29 judge (R29-1, R29-3, R29-4, R29-5a, R29-6, R29-7, R29-12). Pure over the raw event."""
from __future__ import annotations

from r3_oracle import continuity as C
from r3_oracle import ops_model
from r3_oracle.disclosure import low_view
from r3_oracle.disclosure_reads import expected_list_objects, expected_read_object
from r3_shared.recovery import DEPENDENCY_REASONS, RecoveryFormError, validate_reply

REQ_KINDS = ("request", "redeliver")


def _form_bad(status, body):
    if status in ("UNAVAILABLE", "UNKNOWN", "DENIED") and isinstance(body, dict):
        reason = body.get("reason")
        if status == "DENIED" and ("dependency" in body or reason in DEPENDENCY_REASONS):
            return "DENIED names a dependency"
        if status != "DENIED" and (reason in DEPENDENCY_REASONS):
            try:
                validate_reply(status, body)
            except RecoveryFormError as exc:
                return str(exc)[:120]
    return None


def _mis(row, kind, rec):
    row["mis"].setdefault(kind, []).append(rec)
    row["classes"].setdefault("misclassified_dependency_failure", []).append({"kind": kind, **rec})


def _unrelated(row, phi, graph, dom, kind, op, t, progressed):
    deps = set(C.decision_deps(graph, dom, kind, op))
    for node in phi.down(t):
        if node not in deps:
            u = row["unrelated"].setdefault(node, [0, 0])
            u[0] += 1
            u[1] += 1 if progressed else 0


def _request(R, row, e, ctx, phi, versions, renew, crashed, rep, state, process_marks, cw, base, ops, graph, dom, doc_at):
    from .judge import active
    t, rid, op, args = e["t"], e["rid"], e["operation"], e["args"]
    if e.get("err") == "no_host":
        row["req"].append({"n": e["n"], "t": t, "rid": rid, "k": e["k"], "skipped": "no_host"})
        return
    res, err = e.get("res"), e.get("err")
    status, body = (res["status"], res["body"]) if res else (None, {})
    cls = C.classify({"kind": "request", "op": op, "t": t, "rid": rid}, phi, graph, dom, renew, versions, crashed)
    dec, akey = rep.decide(doc_at(t), e["principal"], None, op, args, base + t, rid)
    was = rid in state["committed"]
    m = process_marks(e)
    committed = was or m is not None
    spec = ops_model.op_of(ops, op)
    input_invalid = spec is None or not ops_model.validate_args(spec, args)[0]
    rec = {"n": e["n"], "t": t, "rid": rid, "k": e["k"], "op": op, "cls": cls.kind, "down": cls.down, "strict": cls.strict, "status": status or err,
           "reason": body.get("reason") if isinstance(body, dict) else None, "dep": body.get("dependency") if isinstance(body, dict) else None,
           "oracle": dec.kind, "committed": committed, "eligible": False, "progressed": False, "spurious": None, "fclasses": active(cw, t),
           "phi": sorted(phi.down(t))}
    if e.get("tag") == "stale":                     # F6: truly stale-sensitive = OK under version 0, not OK under the version in force
        old, _ = rep.decide(versions[0]["doc"], e["principal"], None, op, args, base + t, None)
        rec["stale_sensitive"] = old.kind == "OK" and dec.kind != "OK"
    row["req"].append(rec)
    bad = _form_bad(status, body)
    if bad and cls.kind != C.SAFE:
        _mis(row, status, {"rid": rid, "t": t, "why": bad})
    stream = R.get("stream")
    if status == "OK":
        if not committed:
            row["classes"].setdefault("false_success", []).append({"rid": rid, "t": t, "why": "OK reply, no commit in world_log"})
        elif stream and (stream, rid) not in ctx.anchor:
            row["classes"].setdefault("unanchored_ack", []).append({"rid": rid, "t": t, "why": "OK reply without an anchor entry"})
        elif stream and ctx.anchor_seq.get((stream, rid)) is not None and isinstance(e.get("anchor_head_at_reply"), int) \
                and 0 <= e["anchor_head_at_reply"] < ctx.anchor_seq[(stream, rid)]:
            row["classes"].setdefault("unanchored_ack", []).append(          # G5-E20: the entry must precede the reply in the transcript
                {"rid": rid, "t": t, "why": "anchor entry appended after the reply", "entry_seq": ctx.anchor_seq[(stream, rid)],
                 "head_at_reply": e["anchor_head_at_reply"]})
        if cls.kind == C.BLOCKED or (cls.kind == C.UNRESOLVED and cls.down and not committed):
            _mis(row, "OK", {"rid": rid, "t": t, "down": cls.down, "why": "OK while a decision dependency is down"})
    elif status is not None and cls.kind in (C.BLOCKED, C.UNRESOLVED) and cls.down:
        ok, why = C.blocked_reply_ok(cls, status, body, input_invalid, ctx.reason_map)
        if not ok:
            _mis(row, status, {"rid": rid, "t": t, "down": cls.down, "why": why})
    elif status is not None and cls.kind == C.SAFE:
        if status == "UNAVAILABLE" and isinstance(body, dict) and body.get("reason") == "dependency_unavailable":
            rec["spurious"] = body.get("dependency")
    if (cls.kind == C.SAFE and cls.strict and dec.kind == "OK" and dec.outcome is not None and dec.outcome.effects and not was
            and e["k"] == "request" and rid not in crashed and not e.get("attacker") and e.get("tag") not in ("redeliver", "rc2_redeliver")):
        rec["eligible"], rec["progressed"] = True, status == "OK" and committed
        _unrelated(row, phi, graph, dom, "request", op, t, rec["progressed"])


def _read(R, row, e, phi, graph, dom, renew, versions, rep, doc_at, ops, cw):
    from .judge import active
    t = e["t"]
    if e.get("err") == "no_host":
        return
    res, err = e.get("res"), e.get("err")
    status, body = (res["status"], res["body"]) if res else (None, {})
    cls = C.classify({"kind": "read", "op": None, "t": t, "rid": None}, phi, graph, dom, renew, versions)
    lv = low_view(rep.snap, doc_at(t), e["principal"], ops)
    a = e["args"]
    exp = (expected_read_object(lv, f"{a['type']}:{a['key']}") if e["operation"] == "get" else expected_list_objects(lv, a.get("type", "")))
    rec = {"n": e["n"], "t": t, "k": "read", "op": "read:" + e["operation"], "cls": cls.kind, "down": cls.down, "strict": cls.strict,
           "status": status or err, "reason": body.get("reason") if isinstance(body, dict) else None,
           "dep": body.get("dependency") if isinstance(body, dict) else None, "oracle": exp[0], "committed": False, "eligible": False,
           "progressed": False, "spurious": None, "fclasses": active(cw, t), "rid": None, "phi": sorted(phi.down(t))}
    row["req"].append(rec)
    if status == "OK":
        if (exp[0], exp[1]) != ("OK", body):
            row["classes"].setdefault("disclosure_leak", []).append({"t": t, "principal": e["principal"], "args": a, "got": body, "oracle": list(exp)})
        if cls.kind == C.BLOCKED:
            _mis(row, "OK", {"t": t, "down": cls.down, "why": "read served while AUTH is down past the lease"})
    elif status is not None and cls.kind == C.BLOCKED and cls.down:
        ok, why = C.blocked_reply_ok(cls, status, body, False, {})
        if not ok:
            _mis(row, status, {"t": t, "down": cls.down, "why": why})
    elif status == "UNAVAILABLE" and cls.kind == C.SAFE and isinstance(body, dict) and body.get("reason") == "dependency_unavailable":
        rec["spurious"] = body.get("dependency")
    if cls.kind == C.SAFE and cls.strict and exp[0] == "OK":
        rec["eligible"], rec["progressed"] = True, status == "OK" and body == exp[1]
        _unrelated(row, phi, graph, dom, "read", None, t, rec["progressed"])
