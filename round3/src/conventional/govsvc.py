"""Constitutional service (PROT-H25 s3): ONE entry point `constitutional`, one world transaction and one `governance` mark
per OK action; refusals roll back and write nothing. Policy is DATA (the governance document) evaluated by the generic
`govproc.Procedure`; this module is the procedure SERVICE (case table, judgments, emergencies) and contains no
per-domain or per-model decision code (author decision 1)."""
from __future__ import annotations

import contextlib
import sqlite3
from types import SimpleNamespace

from r3_shared import constitutional as K
from r3_shared.governance import validate_governance, EMERGENCY_OP
from r3_shared.authgraph import scope_covers, scope_subset
from r3_shared.variant import CallResult

from . import store
from .abort import _Abort
from .govbook import CaseBook
from .govproc import ALLOW, AWAITING, BIG, DENY, Procedure, Route
from .govstore import GovStore
from .histledger import LedgerUnresolved
from .models_gen import OPERATION_MODELS
from .policy import Decision
from .validation import RequestInvalid, validate_inputs

_DECL = tuple((i["name"], i["type"], i["required"]) for i in K.EMERGENCY_DECLARE_OP["inputs"])


def _bad(reason: str, status: str = "INVALID") -> _Abort:
    return _Abort(status, K.refusal_body(reason))


class GovernanceOps:
    # -- lifecycle ---------------------------------------------------------------------------------------
    def _gov_init(self, h, doc: dict | None) -> None:
        self._gstore = GovStore(self.history)
        self._gstore.init(h)
        self._book, self._govdoc, self._proc = CaseBook(), None, None
        if doc is not None:
            validate_governance(doc, self._policy.doc, self._spec)
            digest = K.digest(doc)
            self._gstore.put_doc(h, digest, doc)
            self._gstore.set_initial(h, digest)
            self._gov_restore(h)  # a fresh deployment over an existing world continues its case lineage

    def _gov_use(self, doc: dict | None) -> None:
        self._govdoc = doc
        self._proc = Procedure(doc, self._mutants) if doc is not None else None

    def _gov_restore(self, h) -> None:
        """restart(): document = last set_governance mark's version (else the deployed one); cases from the marks."""
        self._book = CaseBook()
        self._book.refold(h, self._gstore)
        digest = self._book.gov_versions[-1][1] if self._book.gov_versions else self._gstore.initial(h)
        doc = self._gstore.get_doc(h, digest) if digest else None
        if digest and doc is None:
            raise LedgerUnresolved("governance document blob missing")
        self._gov_use(doc)

    def _first_tx(self, h, tx):
        def f(bound: int):
            r = h._con.execute("SELECT seq, tick FROM world_log WHERE kind='mark' AND tick>=? ORDER BY seq LIMIT 1",
                               (bound,)).fetchone()
            if r:
                return (r[0], r[1])
            return (BIG, tx.tick) if tx.tick >= bound else None
        return f

    # -- helpers -----------------------------------------------------------------------------------------
    @staticmethod
    def _res(op: str, args) -> list[tuple[str, str]]:
        m = OPERATION_MODELS.get(op)
        if m is None or not isinstance(args, dict):
            return []
        return [(m.RESOURCES[n], v) for n, v in args.items() if n in m.RESOURCES and isinstance(v, str)]

    def governed(self, op: str, resources) -> bool:
        return self._proc is not None and bool(self._proc.covering(op, resources))

    def _route(self, case) -> Route | str:
        return self._proc.route(case.operation, self._res(case.operation, case.args))

    def _sees(self, case, sub: str) -> bool:
        if sub == case.requester:
            return True
        rt = self._route(case)
        if not isinstance(rt, Route):
            return False
        names = set(rt.bodies) | ({rt.matter["review"]["by"]} if rt.matter["review"] else set())
        return any(sub in self._proc.bodies[b]["members"] for b in names if b in self._proc.bodies)

    def _case(self, g, a) -> object:
        c = self._book.cases.get(a["case"])
        if c is None or not self._sees(c, g.sub):
            raise _bad("unknown_case")
        return c

    def _fin(self, g, case):
        rt = self._route(case)
        return rt, (self._proc.final(case, rt, g.tick, g.ft) if isinstance(rt, Route) else None)

    # -- entry points ------------------------------------------------------------------------------------
    def constitutional(self, token: str, action: dict, request_id: str) -> CallResult:
        with self._lock:
            if self.crashed:
                return CallResult("UNAVAILABLE", {"reason": "crashed"})
            if self._authority_unresolved:
                return CallResult("UNAVAILABLE", {"reason": "history_unresolved"})
            sub = self.authenticate(token)
            if sub is None:
                return CallResult("DENIED", K.refusal_body("token"))
            if not isinstance(request_id, str) or not request_id.strip() or K.check_action(action):
                return CallResult("INVALID", K.refusal_body("schema"))
            if self._proc is None:
                return CallResult("INVALID", K.refusal_body("no_governance"))
            h = self._factory("conventional-service")
            try:
                try:
                    res = self._gtx(h, sub, action, request_id)
                except _Abort as ab:
                    res = ab.result
                except (sqlite3.Error, ConnectionError, LedgerUnresolved):
                    return CallResult("UNAVAILABLE", {"reason": "dependency_unavailable"})
                if res.status == "OK" and not res.body.get("replayed") and self._armed == "after_commit":
                    return self._crash_now().result
                return CallResult(res.status, {k: v for k, v in res.body.items() if k != "replayed"}
                                  if action["kind"] not in ("execute", "act") else res.body)
            finally:
                h.close()

    def _gtx(self, h, sub: str, a: dict, rid: str) -> CallResult:
        fp = store.fingerprint(sub, None, "constitutional", a)
        with h.transaction(tag="governance") as tx:
            self._book.refold(h, self._gstore)
            prior = self._book.by_rid.get(rid)
            if prior is not None:
                if prior["fp"] != fp:
                    raise _Abort("INVALID", {"reason": "idempotency_key_reuse"})
                return CallResult(prior["status"], {**prior["body"], "replayed": True})
            g = SimpleNamespace(h=h, tx=tx, sub=sub, rid=rid, tick=tx.tick, ft=self._first_tx(h, tx), fp=fp)
            body, mark, extra = getattr(self, "_g_" + a["kind"])(g, a)
            if self._armed == "before_commit":
                raise self._crash_now()
            seq = tx.mark("governance", mark)
            self._gstore.put(h, seq, {"rid": rid, "fp": fp, "status": "OK", "body": body, **extra})
        return CallResult("OK", body)

    # -- propose (3.1, 3.5) --------------------------------------------------------------------------------
    def _g_propose(self, g, a):
        if a["case"] in self._book.cases:
            raise _bad("duplicate_case")
        op, args = a["operation"], a["args"]
        try:
            if op == EMERGENCY_OP:
                validate_inputs(_DECL, args)
            elif op in OPERATION_MODELS:
                OPERATION_MODELS[op].from_args(args)
            else:
                raise RequestInvalid("unknown_operation")
        except RequestInvalid:
            raise _bad("schema")
        res = self._res(op, args)
        rt = self._proc.route(op, res)
        if rt in ("not_governed", "matter_conflict"):
            raise _bad(rt)
        obo = a["on_behalf_of"]
        if not self._policy.decide(g.sub, obo, op, res, g.tick).allowed:
            raise _bad("no_authority", "DENIED")
        if rt == "precedence_unresolved":
            raise _bad(rt, "DENIED")
        if op == EMERGENCY_OP:
            self._check_declare(args, g.tick)
        mark = K.governance_mark("propose", case=a["case"], requester=g.sub, on_behalf_of=obo, operation=op, args=args,
                                 bodies=list(rt.bodies))
        return K.ok_body("propose", case=a["case"], bodies=list(rt.bodies)), mark, {"args": args}

    def _check_declare(self, args: dict, tick: int) -> None:
        em, sc, gr = self._govdoc["emergency"], args["scope"], args["grantees"]
        if em is None:
            raise _bad("scope_amplification", "DENIED")
        okscope = isinstance(sc, dict) and set(sc) == {"operations", "resources"} \
            and isinstance(sc["operations"], list) and isinstance(sc["resources"], list)
        if not okscope or not isinstance(gr, list) or not all(isinstance(x, str) for x in gr):
            raise _bad("schema")
        if not scope_subset(sc, em["ceiling"]):
            raise _bad("scope_amplification", "DENIED")
        if args["expires_at"] > tick + em["max_duration"]:
            raise _bad("emergency_too_long")
        if not set(gr) <= set(self._proc.bodies[em["grantees_from"]]["members"]):
            raise _bad("not_grantee", "DENIED")

    # -- judge / appeal (3.2, 3.3) ----------------------------------------------------------------------------
    def _g_judge(self, g, a):
        c = self._case(g, a)
        rt = self._route(c)
        stage, bodies = a["stage"], ()
        if isinstance(rt, Route):
            if stage == "decision":
                bodies = rt.bodies
            elif c.appeal is not None and rt.matter["review"]:
                bodies = (rt.matter["review"]["by"],)
        if not any(g.sub in self._proc.eligible(b, c.requester) for b in bodies):
            raise _bad("not_eligible", "DENIED")
        res = self._proc.decision(c, rt, g.ft) if stage == "decision" else self._proc.review(c, rt)
        if res.outcome != AWAITING:
            raise _bad("stage_closed")
        if any(j.stage == stage and j.judge == g.sub for j in c.judgments):
            raise _bad("already_judged")
        mark = K.governance_mark("judge", case=c.id, stage=stage, judge=g.sub, value=a["value"], merit=a["merit"])
        return K.ok_body("judge", case=c.id, stage=stage), mark, {"merit": a["merit"]}

    def _g_appeal(self, g, a):
        c = self._case(g, a)
        rt = self._route(c)
        if not isinstance(rt, Route) or rt.matter["review"] is None:
            raise _bad("not_reviewable")
        dec = self._proc.decision(c, rt, g.ft)
        if dec.outcome == AWAITING:
            raise _bad("not_decided")
        if g.sub != c.requester and not any(g.sub in self._proc.bodies[b]["members"] for b in rt.bodies):
            raise _bad("not_party", "DENIED")
        if c.appeal is not None:
            raise _bad("already_appealed")
        if g.tick >= dec.tick + rt.matter["review"]["window"]:
            raise _bad("window_closed", "DENIED")
        return K.ok_body("appeal", case=c.id), K.governance_mark("appeal", case=c.id, by=g.sub), {}

    # -- execute (3.4) ----------------------------------------------------------------------------------------
    def _g_execute(self, g, a):
        c = self._case(g, a)
        if g.sub != c.requester:
            raise _bad("not_requester", "DENIED")
        if c.executed is not None:
            raise _Abort(c.executed["status"], {**c.executed["body"], "replayed": True})
        rt, fin = self._fin(g, c)
        if fin is None or fin.outcome == AWAITING:
            raise _bad("oracle_needed", "DENIED")
        if fin.outcome == "NOT_FINAL":
            raise _bad("not_final", "DENIED")
        if fin.outcome == DENY:
            raise _bad("case_denied", "DENIED")
        res = self._res(c.operation, c.args)
        d = self._policy.decide(c.requester, c.obo, c.operation, res, g.tick)
        if not d.allowed:
            raise _bad("no_authority", "DENIED")
        if c.operation == EMERGENCY_OP:  # activation is derived from the final outcome; no canonical effect
            body = {"operation": c.operation, "effects": 0, "request_id": g.rid, "authority_version": self._policy.version}
        else:
            body = self._run_case_op(g, c, d)
        mark = K.governance_mark("execute", case=c.id, rule=fin.rule, basis=list(fin.basis))
        return body, mark, {}

    def _run_case_op(self, g, c, d) -> dict:
        from .service import BoundRequest
        from .provenance import DecisionCtx
        model = OPERATION_MODELS[c.operation]
        inputs = model.from_args(c.args).inputs()
        from types import MappingProxyType
        b = BoundRequest(c.requester, c.obo, c.operation, MappingProxyType(inputs),
                         tuple((model.RESOURCES[n], v) for n, v in inputs.items() if n in model.RESOURCES),
                         g.rid, self._policy.version, store.fingerprint(c.requester, c.obo, c.operation, inputs))
        dc = DecisionCtx("constitutional", g.rid, c.requester, c.obo, c.operation, c.args)
        out = self._txn(g.h, g.tx, self._ops[c.operation], model, b, c.args, True, dc, pre=d, gate=False)
        return out.body

    # -- emergencies (3.5) ------------------------------------------------------------------------------------
    def _emergency(self, g, eid):
        for c in self._book.cases.values():
            if c.operation == EMERGENCY_OP and c.args.get("emergency") == eid:
                rt = self._proc.route(EMERGENCY_OP, [])
                if isinstance(rt, Route) and self._proc.final(c, rt, g.tick, g.ft).outcome == ALLOW:
                    return c, rt
        return None

    def _g_act(self, g, a):
        eid, op, args = a["emergency"], a["operation"], a["args"]
        found = None if eid in self._book.ends else self._emergency(g, eid)
        if found is None:
            raise _bad("emergency_inactive", "DENIED")
        em = found[0].args
        res = self._res(op, args)
        if g.sub not in em["grantees"]:
            raise _bad("not_grantee", "DENIED")
        if not scope_covers(em["scope"], op, res):
            raise _bad("out_of_emergency_scope", "DENIED")
        if g.tick >= em["expires_at"] and "emergency_no_expiry" not in self._mutants:
            raise _bad("emergency_expired", "DENIED")
        if self._policy._matching(g.sub, op, res, "deny"):
            raise _bad("no_authority", "DENIED")
        d = Decision(True, "allowed", g.sub, None, op, self._policy.version)
        if op not in OPERATION_MODELS:
            raise _Abort("INVALID", {"reason": "unknown_operation"})
        try:
            OPERATION_MODELS[op].from_args(args)
        except RequestInvalid as exc:
            raise _Abort("INVALID", {"reason": exc.reason})
        c = SimpleNamespace(requester=g.sub, obo=None, operation=op, args=args)
        body = self._run_case_op(g, c, d)
        return body, K.governance_mark("act", emergency=eid, operation=op, args=args), {}

    def _g_end(self, g, a):
        eid = a["emergency"]
        found = None if eid in self._book.ends else self._emergency(g, eid)
        if found is None:
            raise _bad("emergency_inactive", "DENIED")
        if not any(g.sub in self._proc.bodies[b]["members"] for b in found[1].bodies):
            raise _bad("not_grantee", "DENIED")
        return K.ok_body("end", emergency=eid), K.governance_mark("end", emergency=eid), {"by": g.sub}

    # -- set_governance (3.6) / case_state ---------------------------------------------------------------------
    def set_governance(self, doc: dict) -> None:
        with self._lock:
            if self.crashed:
                raise RuntimeError("deployment is crashed; restart() first")
            validate_governance(doc, self._policy.doc, self._spec)  # ValueError: nothing changes
            h = self._factory("conventional-service")
            try:
                with h.transaction(tag="governance") as tx:
                    digest = K.digest(doc)
                    self._gstore.put_doc(h, digest, doc)
                    seq = tx.mark("governance", K.governance_mark("set_governance", doc=doc))
                    self._gstore.put(h, seq, {"doc": digest})
            finally:
                h.close()
            self._gov_use(doc)

    def case_state(self, case_id: str) -> dict | None:
        with self._lock:
            if self.crashed or self._proc is None:
                return None
            h = self._factory("conventional-service")
            try:
                self._book.refold(h, self._gstore)
                c = self._book.cases.get(case_id)
                if c is None:
                    return None
                rt = self._route(c)
                now = self._clock.now()
                tx = SimpleNamespace(tick=now)
                fin = self._proc.final(c, rt, now, self._first_tx(h, tx)) if isinstance(rt, Route) else None
                return {"case": c.id, "requester": c.requester, "operation": c.operation, "args": dict(c.args),
                        "stage_outcomes": {"decision": fin.decision.outcome if fin else AWAITING,
                                           "review": fin.review.outcome if fin and fin.review else None},
                        "final": fin.outcome if fin else AWAITING, "executed": c.executed is not None}
            finally:
                h.close()
