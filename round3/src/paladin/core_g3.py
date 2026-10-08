"""Gate 3 part of the request core (H25): constitutional actions, governance in force, base-authority re-checks.

Mixed into `paladin.core.Core`. Durable record = the `governance` marks in the world_log (PROT-H25 R25-7); the case args and
the request ids behind judgments live beside them in the ledger meta (`case:<id>`, `jr:<case>:<stage>:<judge>`, `exec:<case>`,
`gov:<version>`), written INSIDE the transaction. The CaseBook (paladin.procedure) is rebuilt from marks + meta at restart.
Governance is compiled once per document (paladin.govir) and evaluated by ONE generic procedure for every model/domain.
"""
from __future__ import annotations

import copy
import json

from paladin import evid
from paladin.core_g2 import Rollback
from paladin.engine import Principal, typecheck
from paladin.engine.authority import Resource
from paladin.engine.state import State
from paladin.govhooks import GovAct, GovExec, refusal
from paladin.govir import DECLARE, compile_governance, conflict, decide_bodies
from paladin.procedure import CaseBook
from r3_shared.authgraph import scope_subset
from r3_shared.authspec import allowed_operations
from r3_shared.constitutional import EMERGENCY_DECLARE_OP, check_action, digest, governance_mark
from r3_shared.variant import CallResult


def _inv(reason: str) -> Rollback:
    return refusal("INVALID", reason)


def _deny(reason: str) -> Rollback:
    return refusal("DENIED", reason)


class G3Mixin:
    def g3_init(self, governance: dict | None) -> None:
        self._gov_default, self.book, self.gov_fault = governance, None, None
        self.type_names = [t["name"] for t in self.ops_spec["resource_types"]]
        self.link_names = [lk["name"] for lk in self.ops_spec["link_types"]]
        self.subs, self._nsub = {}, 0
        self.g3_rebuild()

    # ---- governance in force, rebuilt from marks + meta ------------------------------------------------
    def _marks(self) -> list:
        rows = self._svc._con.execute("SELECT seq,tick,data_json FROM world_log WHERE kind='mark' AND ref='governance' "
                                      "ORDER BY seq").fetchall()
        return [(s, t, json.loads(d)) for s, t, d in rows]

    def refs_of(self, op: str, args) -> list:
        if op == DECLARE or op not in self.ops or not isinstance(args, dict):
            return []
        try:
            return evid.input_refs(self.ops_spec, op, args)
        except (KeyError, TypeError):
            return []

    def g3_rebuild(self) -> None:
        d0, book = self._gov_default, None
        if d0 is not None:
            book = CaseBook(compile_governance(d0, digest(d0)), self.mutants)
        for seq, tick, p in self._marks():
            op = p["op"]
            if op == "set_governance":
                doc = self.ledger.get_meta("gov:" + p["version"])
                if doc is None:
                    self.gov_fault = f"governance document {p['version'][:12]} missing"
                    break
                g = compile_governance(doc, p["version"])
                if book is None:
                    book = CaseBook(g, self.mutants)
                else:
                    book.apply_governance(seq, tick, g)
            elif book is None:
                continue
            elif op == "propose":
                meta = self.ledger.get_meta("case:" + p["case"])
                args = meta["args"] if meta and digest(meta["args"]) == p["args_digest"] else None
                book.apply_propose(seq, tick, p["case"], p["requester"], p["on_behalf_of"], p["operation"], args,
                                   self.refs_of(p["operation"], args))
            elif op == "judge":
                rid = self.ledger.get_meta(f"jr:{p['case']}:{p['stage']}:{p['judge']}")
                book.apply_judge(seq, tick, p["case"], p["stage"], p["judge"], p["value"], rid)
            elif op == "appeal":
                book.apply_appeal(seq, tick, p["case"], p["by"])
            elif op == "end":
                c = book.emergency(p["emergency"], tick)
                if c is not None:
                    book.apply_end(seq, tick, c.id)
            elif op in ("execute", "act"):
                book.settle(seq, tick)
                if op == "execute":
                    book.cases[p["case"]].executed = self.ledger.get_meta("exec:" + p["case"])
        self.book = book

    # ---- base authority (world-independent) -----------------------------------------------------------
    def pre_authority(self, who: Principal, op: str, args: dict, deny_only: bool = False) -> bool:
        """The Engine's authority decision over the DECLARED resources of the request (no world read): PROT-H26 s3.2 puts
        authority before existence. With deny_only: True iff no deny rule applies (emergency act, s3.5)."""
        spec = self.eng.model.get("actions", op)
        res = []
        for p in spec.inputs:
            if p.pname in args:
                res += [Resource(t, k, t) for t, k in typecheck.ref_values(p.type, args[p.pname])]
        res += [Resource(e.target, None, e.target) for e in spec.effects]
        view = self.eng.read_view(State(self.eng.model, {}, {}))
        dec = self.eng.dispatch("authority_rules", "decide", None, refs=spec.auth_refs, principal=who,
                                capability=f"action:{op}", resources=tuple(res), view=view)
        return (not dec.deny and not dec.errors) if deny_only else dec.allowed

    def base_denied(self, sub: str, obo, op: str, args, tick: int, d: dict | None = None) -> bool:
        """PROT-H23/H24 base authority of `sub` (optionally for `obo`) for (op, args), decided at `tick`."""
        if op == DECLARE:
            return sub not in self.booted.principals or DECLARE not in allowed_operations(self.auth, sub, [DECLARE])
        who = self.principal(sub, obo, op)
        if isinstance(who, CallResult):
            return True
        if obo is not None and self.delegator.get(sub) is None and self.edge_check(sub, obo, op, args, tick, d if d is not None else {}) is not None:
            return True
        return not self.pre_authority(who, op, args)

    def case_required(self, who_pid: str, op: str, args) -> bool:
        """A GOVERNED request needs a case (s3.4): ordinary call_tool/direct of it is refused."""
        if self.book is None or not self.book.g.covering(op, self.refs_of(op, args)):
            return False
        if "domain_privilege_branch" in self.mutants and self.domain == "project" and who_pid.endswith("-1"):
            return False   # MUTANT domain_privilege_branch: a domain/fixture-identity branch in the decision path
        return True

    # ---- constitutional entry (PROT-H25 s3) -------------------------------------------------------------
    def constitutional(self, sub: str, action: dict, rid) -> CallResult:
        from paladin.core import fingerprint, plain  # noqa: PLC0415
        if self.auth_fault is not None or self.gov_fault is not None:
            return CallResult("UNAVAILABLE", {"reason": "history_unresolved"})
        if check_action(action) is not None or not isinstance(rid, str) or not rid:
            return CallResult("INVALID", {"reason": "schema"})
        if sub not in self.booted.principals:
            return CallResult("DENIED", {"reason": "token"})
        fp = fingerprint(sub, "constitutional", action)
        with self._guard():
            led = self.ledger.get(rid)
            if led is not None:
                if led["state"] != "COMMITTED":
                    return CallResult("UNAVAILABLE", {"reason": "request in flight"})
                if led["fp"] != fp:
                    return CallResult("INVALID", {"reason": "request_id already used for a different request"})
                return CallResult(led["status"], plain(led["body"] or {}))
            if self.book is None:
                return CallResult("INVALID", {"reason": "no_governance"})
            try:
                return getattr(self, "_g_" + action["kind"])(sub, action, rid, fp)
            except Rollback as r:
                return CallResult(r.result.status, {"reason": r.result.body["reason"]})

    def _g_commit(self, sub, rid, fp, kind, build) -> CallResult:
        """One world transaction with exactly one `governance` mark; refusals (Rollback) write nothing."""
        persisted = False
        try:
            with self._svc.transaction(tag="governance") as tx:
                payload, metas, body, post = build(tx)
                seq = tx.mark("governance", payload)
                self.hook("before_commit")
                persisted = True
                for k, v in metas:
                    self.ledger.put_meta(k, v)
                self.ledger.commit_row(rid, fp, sub, None, "constitutional:" + kind, "OK", body)
        except BaseException as exc:
            from paladin.core import Crash  # noqa: PLC0415
            if persisted and not isinstance(exc, (Crash, Rollback)):
                self.ledger.drop(rid)
            raise
        post(seq, tx.tick)
        self.hook("after_commit")
        return CallResult("OK", body)

    def _case(self, sub: str, a: dict):
        c = self.book.cases.get(a["case"])
        if c is None or sub not in self.book.seers(c):
            raise _inv("unknown_case")
        return c

    def _g_propose(self, sub, a, rid, fp):
        def build(tx):
            book, tick, op, args, obo = self.book, tx.tick, a["operation"], a["args"], a["on_behalf_of"]
            if a["case"] in book.cases:
                raise _inv("duplicate_case")
            odef = EMERGENCY_DECLARE_OP if op == DECLARE else self.ops.get(op)
            if odef is None or self.schema_problem_def(odef, args) is not None:
                raise _inv("schema")
            args = json.loads(json.dumps(args))
            refs = self.refs_of(op, args)
            ms = book.g.covering(op, refs)
            em = book.g.emergency
            if not ms or (op == DECLARE and em is None):
                raise _inv("not_governed")
            if conflict(ms):
                raise _inv("matter_conflict")
            if self.base_denied(sub, obo, op, args, tick):
                raise _deny("no_authority")
            bs, _m, st = decide_bodies(book.g, ms, self.mutants)
            if st == "unresolved":
                raise _deny("precedence_unresolved")
            if op == DECLARE:
                self._declare_checks(args, tick, em)
            payload = governance_mark("propose", case=a["case"], requester=sub, on_behalf_of=obo, operation=op, args=args,
                                      bodies=bs)
            post = lambda seq, t: book.apply_propose(seq, t, a["case"], sub, obo, op, args, refs)  # noqa: E731
            return payload, [("case:" + a["case"], {"args": args})], {"case": a["case"], "bodies": sorted(bs)}, post
        return self._g_commit(sub, rid, fp, "propose", build)

    def _declare_checks(self, args: dict, tick: int, em: dict) -> None:
        sc, gr = args["scope"], args["grantees"]
        ok = (isinstance(sc, dict) and set(sc) == {"operations", "resources"} and isinstance(sc["operations"], list)
              and isinstance(sc["resources"], list) and isinstance(gr, list) and all(isinstance(x, str) for x in gr)
              and all(isinstance(r, dict) and set(r) == {"type", "keys"} for r in sc["resources"]))
        if not ok:
            raise _inv("schema")
        if not scope_subset(sc, em["ceiling"]):
            raise _deny("scope_amplification")
        if args["expires_at"] > tick + em["max_duration"]:
            raise _inv("emergency_too_long")
        if any(x not in self.book.g.bodies[em["grantees_from"]].members for x in gr):
            raise _deny("not_grantee")

    def _g_judge(self, sub, a, rid, fp):
        def build(tx):
            book, c, tick, stage = self.book, self._case(sub, a), tx.tick, a["stage"]
            if stage == "decision":
                elig = {m for b in book.bodies(c) for m in book.eligible(c, b)}
                closed = book.decision(c, tick) is not None
            else:
                rb = book.review_body(c)
                elig = set(book.eligible(c, rb)) if (rb and c.appeal is not None) else set()
                closed = c.decided["review"] is not None
            if sub not in elig:
                raise _deny("not_eligible")
            if closed:
                raise _inv("stage_closed")
            if any(j["stage"] == stage and j["judge"] == sub for j in c.judgments):
                raise _inv("already_judged")
            payload = governance_mark("judge", case=c.id, stage=stage, judge=sub, value=a["value"], merit=a["merit"])
            post = lambda seq, t: book.apply_judge(seq, t, c.id, stage, sub, a["value"], rid)  # noqa: E731
            return payload, [(f"jr:{c.id}:{stage}:{sub}", rid)], {"case": c.id, "stage": stage}, post
        return self._g_commit(sub, rid, fp, "judge", build)

    def _g_appeal(self, sub, a, rid, fp):
        def build(tx):
            book, c, tick = self.book, self._case(sub, a), tx.tick
            m = book.governing(c)
            if m is None or m.review_by is None:
                raise _inv("not_reviewable")
            d = book.decision(c, tick)
            if d is None:
                raise _inv("not_decided")
            if sub != c.requester and sub not in {x for b in book.bodies(c) for x in book.g.bodies[b].members}:
                raise _deny("not_party")
            if c.appeal is not None:
                raise _inv("already_appealed")
            if tick >= d[2] + m.window:
                raise _deny("window_closed")
            post = lambda seq, t: book.apply_appeal(seq, t, c.id, sub)  # noqa: E731
            return governance_mark("appeal", case=c.id, by=sub), [], {"case": c.id}, post
        return self._g_commit(sub, rid, fp, "appeal", build)

    def _g_end(self, sub, a, rid, fp):
        def build(tx):
            book = self.book
            c = book.emergency(a["emergency"], tx.tick)
            if c is None:
                raise _deny("emergency_inactive")
            if sub not in {x for b in book.bodies(c) for x in book.g.bodies[b].members}:
                raise _deny("not_eligible")
            post = lambda seq, t: book.apply_end(seq, t, c.id)  # noqa: E731
            return governance_mark("end", emergency=a["emergency"]), [], {"emergency": a["emergency"]}, post
        return self._g_commit(sub, rid, fp, "end", build)

    def _g_execute(self, sub, a, rid, fp):
        c = self._case(sub, a)
        if sub != c.requester:
            raise _deny("not_requester")
        if c.executed is not None:
            return CallResult(c.executed["status"], dict(c.executed["body"]))
        if c.op == DECLARE:   # the emergency's effect is its activation (s3.5): execute only records the final outcome
            def build(tx):
                from paladin.govhooks import final_gate  # noqa: PLC0415
                rule, basis = final_gate(self, c, tx.tick)
                if self.base_denied(sub, c.obo, c.op, c.args, tx.tick):
                    raise _deny("no_authority")
                st = {"status": "OK", "body": {"case": c.id}}

                def post(seq, t):
                    self.book.settle(seq, t)
                    c.executed = st
                return (governance_mark("execute", case=c.id, rule=rule, basis=basis), [("exec:" + c.id, st)],
                        st["body"], post)
            return self._g_commit(sub, rid, fp, "execute", build)
        return self.run(sub, c.obo, c.op, c.args, rid, "direct", GovExec(self, sub, c))

    def _g_act(self, sub, a, rid, fp):
        act = GovAct(self, sub, a, self.refs_of(a["operation"], a["args"]))
        if a["operation"] not in self.ops:   # unknown operation: only the procedural refusals can apply
            with self._svc.transaction(tag="governance") as tx:
                act.before(tx, {})
                raise Rollback(CallResult("UNKNOWN", {"reason": "no such tool"}))
        return self.run(sub, None, a["operation"], a["args"], rid, "direct", act)

    # ---- set_governance, case_state (P1e-2) ------------------------------------------------------------
    def replace_governance(self, doc: dict) -> None:
        from r3_shared.governance import validate_governance  # noqa: PLC0415
        doc = copy.deepcopy(validate_governance(doc, self.auth, self.ops_spec))
        ver = digest(doc)
        with self._guard():
            with self._svc.transaction(tag="governance") as tx:
                seq = tx.mark("governance", governance_mark("set_governance", doc=doc))
                self.ledger.put_meta("gov:" + ver, doc)
            g = compile_governance(doc, ver)
            if self.book is None:
                self.book = CaseBook(g, self.mutants)
            else:
                self.book.apply_governance(seq, tx.tick, g)

    def case_state(self, case_id: str) -> dict | None:
        c = self.book.cases.get(case_id) if self.book is not None else None
        if c is None:
            return None
        tick = self.clock.now()
        dec, st = self.book.decision(c, tick), self.book.final(c, tick)
        return {"case": c.id, "requester": c.requester, "operation": c.op, "args": copy.deepcopy(c.args),
                "stage_outcomes": {"decision": dec[0] if dec else "AWAITING",
                                   "review": c.decided["review"][0] if c.decided["review"] else "AWAITING"},
                "final": st[1] if st[0] == "FINAL" else None, "executed": c.executed is not None}
