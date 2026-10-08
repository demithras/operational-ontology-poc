"""Constitution oracle (ORACLE-AND-HARNESS-G3 A1; PROT-H25 s2-s3): a pure immutable value. `apply(event)` returns a NEW
value; `decide_action(...)` gives the frozen-order verdict at a commit point (seq, tick). Imports r3_shared forms and
r3_oracle only - no variant, no clock, no fixture code. Procedural evaluation lives in const_eval.py; merit is never read."""
from __future__ import annotations

import copy
from typing import NamedTuple

from r3_shared import constitutional as K

from . import authority, const_eval as E, ops_model
from . import scope_v2 as sc
from .authority_v2 import V2, RefAuthority, event
from .const_static import _scope_shape as scope_shape
from .const_static import static_errors

DECL = "emergency:declare"


class Verdict(NamedTuple):
    status: str  # OK | OK_STORED | RUN | DENIED | INVALID | UNDEFINED
    reason: str | None  # None = any reason accepted (frozen text leaves it open)
    mark: dict | None = None
    body: dict | None = None
    run: dict | None = None  # RUN: the operation to evaluate with the H23 model {subject, obo, op, args, emergency}


def to_v2(spec: dict) -> dict:
    """An r3-authority-3 spec decides exactly like its v2 base (the disclosure layer is not authority)."""
    return {**{k: v for k, v in spec.items() if k != "disclosure"}, "spec": V2}


def _r(status, reason):
    return Verdict(status, reason)


class Constitution:
    def __init__(self, ops: dict, s: dict):
        self.ops, self.s = ops, s

    @classmethod
    def from_docs(cls, auth_v3: dict, governance_doc: dict | None, ops_spec: dict) -> "Constitution":
        ra = RefAuthority.from_spec(to_v2(auth_v3))
        docs = {K.digest(governance_doc): governance_doc} if governance_doc is not None else {}
        return cls(ops_spec, {"ra": ra, "doc": governance_doc, "docs": docs, "cases": {}, "ended": {}})

    # -- views -----------------------------------------------------------------------------------------
    @property
    def doc(self):
        return self.s["doc"]

    @property
    def base(self) -> dict:
        return self.s["ra"].view(None).base

    def register_doc(self, doc: dict) -> "Constitution":
        s = dict(self.s)
        s["docs"] = {**s["docs"], K.digest(doc): doc}
        return Constitution(self.ops, s)

    def case(self, cid: str) -> dict | None:
        return self.s["cases"].get(cid)

    def base_allows(self, subject, obo, op, resources, seq, tick):
        return self.s["ra"].decide(subject, obo, op, resources, seq, tick)

    def final(self, cid: str, seq: int, tick: int) -> dict:
        return E.final(self.doc, self.ops, self.s["cases"][cid], seq, tick)

    def stage(self, cid: str, stage: str, seq: int, tick: int) -> dict:
        c = self.s["cases"][cid]
        d = E.decision(self.doc, self.ops, c, seq, tick)
        return d if stage == "decision" else E.review(self.doc, self.ops, c, d, seq)

    def basis(self, cid: str, seq: int, tick: int) -> list[str]:
        return self.final(cid, seq, tick)["basis"]

    def emergency_active(self, eid: str, seq: int, tick: int) -> dict | None:
        """The emergency record if ACTIVE at the commit point (activated, not ended); expiry is checked by `act`."""
        if self.doc is None or self.s["ended"].get(eid, 10 ** 18) < seq:
            return None
        for c in self.s["cases"].values():
            if c["operation"] == DECL and isinstance(c["args"], dict) and c["args"].get("emergency") == eid:
                f = E.final(self.doc, self.ops, c, seq, tick)
                if f["state"] == "FINAL" and f["outcome"] == E.ALLOW:
                    return {"id": eid, "scope": c["args"]["scope"], "expires_at": c["args"]["expires_at"],
                            "grantees": c["args"]["grantees"], "case": c["case"], "bodies": f["dec"]["bodies"]}
        return None

    # -- transitions -----------------------------------------------------------------------------------
    def apply(self, ev: dict) -> "Constitution":
        """ev kinds: {"kind":"action","subject","action","seq","tick","rid"} (an OK constitutional action, state change
        derived from the action alone), {"kind":"set_governance","doc",...}, {"kind":"authority","op","payload","seq","tick"}."""
        s = copy.deepcopy({k: v for k, v in self.s.items() if k not in ("ra", "docs")})
        s["ra"], s["docs"] = self.s["ra"], self.s["docs"]
        k = ev["kind"]
        if k == "authority":
            payload = {"spec": to_v2(ev["payload"]["spec"])} if ev["op"] == "set_authority" else ev["payload"]
            s["ra"] = s["ra"].apply(event(ev["seq"], ev["tick"], ev["op"], payload))
        elif k == "set_governance":
            s["doc"] = ev["doc"]
            s["docs"] = {**s["docs"], K.digest(ev["doc"]): ev["doc"]}
        else:
            self._apply_action(s, ev)
        return Constitution(self.ops, s)

    def _apply_action(self, s, ev):
        a, who, seq, tick = ev["action"], ev["subject"], ev["seq"], ev["tick"]
        kind = a["kind"]
        if kind == "propose":
            s["cases"][a["case"]] = {"case": a["case"], "requester": who, "obo": a["on_behalf_of"],
                                     "operation": a["operation"], "args": a["args"], "pseq": seq, "ptick": tick,
                                     "judgments": [], "appeal": None, "executed": None}
        elif kind == "judge":
            s["cases"][a["case"]]["judgments"].append({"seq": seq, "tick": tick, "stage": a["stage"], "judge": who,
                                                       "value": a["value"], "rid": ev["rid"]})
        elif kind == "appeal":
            s["cases"][a["case"]]["appeal"] = {"by": who, "seq": seq, "tick": tick}
        elif kind == "execute":
            f = E.final(s["doc"], self.ops, s["cases"][a["case"]], seq, tick)
            s["cases"][a["case"]]["executed"] = {"seq": seq, "rule": f["rule"], "basis": f["basis"]}
        elif kind == "end":
            s["ended"][a["emergency"]] = seq

    # -- the frozen check order (PROT-H25 s3) -------------------------------------------------------------
    def decide_action(self, subject: str | None, action, seq: int, tick: int) -> Verdict:
        if subject is None:
            return _r("DENIED", "token")
        if K.check_action(action) is not None:
            return _r("INVALID", "schema")
        if self.doc is None:
            return _r("INVALID", "no_governance")
        return getattr(self, "_" + action["kind"])(subject, action, seq, tick)

    def _propose(self, who, a, seq, tick) -> Verdict:
        if a["case"] in self.s["cases"]:
            return _r("INVALID", "duplicate_case")
        op = K.EMERGENCY_DECLARE_OP if a["operation"] == DECL else ops_model.op_of(self.ops, a["operation"])
        if op is None or not ops_model.schema_valid_args(op, a["args"]):
            return _r("INVALID", "schema")
        res = E.resources_for(self.ops, a["operation"], a["args"])
        st, bodies, ms, _ = E.competent(self.doc, a["operation"], res)
        if st in ("not_governed", "matter_conflict"):
            return _r("INVALID", st)
        if not self.base_allows(who, a["on_behalf_of"], a["operation"], res, seq, tick).allow:
            return _r("DENIED", "no_authority")
        if st != "OK":
            return _r("DENIED", st)
        em = self.doc["emergency"]
        if a["operation"] == DECL and em is not None and em["matter"] in {m["id"] for m in ms}:
            args = a["args"]
            if not (isinstance(args["scope"], dict) and scope_shape(args["scope"])
                    and sc.subset(args["scope"], em["ceiling"])):
                return _r("DENIED", "scope_amplification")
            if args["expires_at"] > tick + em["max_duration"]:
                return _r("INVALID", "emergency_too_long")
            gm = E.body_of(self.doc, em["grantees_from"])["members"]
            if not (isinstance(args["grantees"], list) and all(isinstance(g, str) and g in gm for g in args["grantees"])):
                return _r("DENIED", "not_grantee")
        mark = K.governance_mark("propose", case=a["case"], requester=who, on_behalf_of=a["on_behalf_of"],
                                 operation=a["operation"], args=a["args"], bodies=bodies)
        return Verdict("OK", None, mark, K.ok_body("propose", case=a["case"], bodies=bodies))

    def _visible(self, who, cid):
        c = self.s["cases"].get(cid)
        return c if c is not None and E.sees(self.doc, self.ops, c, who) else None

    def _judge(self, who, a, seq, tick) -> Verdict:
        c = self._visible(who, a["case"])
        if c is None:
            return _r("INVALID", "unknown_case")
        d = E.decision(self.doc, self.ops, c, seq, tick)
        if a["stage"] == "decision":
            bodies, closed = d["bodies"], d["outcome"] != E.AWAIT
        else:
            rv = d["matter"]["review"] if d["matter"] else None
            bodies = [rv["by"]] if rv and E.appealed(c, seq) else []
            closed = bool(bodies) and E.review(self.doc, self.ops, c, d, seq)["outcome"] != E.AWAIT
        if not any(who in E.eligible(self.doc, b, c["requester"]) for b in bodies):
            return _r("DENIED", "not_eligible")
        if closed:
            return _r("INVALID", "stage_closed")
        if any(j["judge"] == who and j["stage"] == a["stage"] for j in c["judgments"]):
            return _r("INVALID", "already_judged")
        mark = K.governance_mark("judge", case=a["case"], stage=a["stage"], judge=who, value=a["value"], merit=a["merit"])
        return Verdict("OK", None, mark, K.ok_body("judge", case=a["case"], stage=a["stage"]))

    def _appeal(self, who, a, seq, tick) -> Verdict:
        c = self._visible(who, a["case"])
        if c is None:
            return _r("INVALID", "unknown_case")
        d = E.decision(self.doc, self.ops, c, seq, tick)
        rv = d["matter"]["review"] if d["matter"] else None
        if rv is None:
            return _r("INVALID", "not_reviewable")
        if d["outcome"] == E.AWAIT:
            return _r("INVALID", "not_decided")
        if who != c["requester"] and not any(who in E.body_of(self.doc, b)["members"] for b in d["bodies"]):
            return _r("DENIED", "not_party")
        if E.appealed(c, seq):
            return _r("INVALID", "already_appealed")
        if tick >= d["tick"] + rv["window"]:
            return _r("DENIED", "window_closed")
        return Verdict("OK", None, K.governance_mark("appeal", case=a["case"], by=who), K.ok_body("appeal", case=a["case"]))

    def _execute(self, who, a, seq, tick) -> Verdict:
        c = self._visible(who, a["case"])
        if c is None:
            return _r("INVALID", "unknown_case")
        if who != c["requester"]:
            return _r("DENIED", "not_requester")
        if c["executed"] is not None:
            return Verdict("OK_STORED", None)
        f = E.final(self.doc, self.ops, c, seq, tick)
        if f["state"] == E.AWAIT:
            return _r("DENIED", "oracle_needed")
        if f["state"] == "NOT_FINAL":
            return _r("DENIED", "not_final")
        if f["outcome"] == E.DENY:
            return _r("DENIED", "case_denied")
        res = E.resources_for(self.ops, c["operation"], c["args"])
        if not self.base_allows(c["requester"], c["obo"], c["operation"], res, seq, tick).allow:
            return _r("DENIED", "no_authority")
        if c["operation"] == DECL:
            return _r("UNDEFINED", "execute_declare")
        mark = K.governance_mark("execute", case=a["case"], rule=f["rule"], basis=f["basis"])
        dec = self.base_allows(c["requester"], c["obo"], c["operation"], res, seq, tick)
        subj, obo = (c["obo"], None) if dec.valid_paths else (c["requester"], c["obo"])
        return Verdict("RUN", None, mark, None, {"subject": subj, "obo": obo, "op": c["operation"], "args": c["args"],
                                                 "emergency": False})

    def _act(self, who, a, seq, tick) -> Verdict:
        em = self.emergency_active(a["emergency"], seq, tick)
        if em is None:
            return _r("DENIED", "emergency_inactive")
        if not isinstance(em["grantees"], list) or who not in em["grantees"]:
            return _r("DENIED", "not_grantee")
        res = E.resources_for(self.ops, a["operation"], a["args"])
        if not sc.covers(em["scope"], a["operation"], res):
            return _r("DENIED", "out_of_emergency_scope")
        if tick >= em["expires_at"]:
            return _r("DENIED", "emergency_expired")
        p = authority._principal(self.base, who)
        if p is None or authority._matching(self.base, "deny", p, a["operation"], res):
            return _r("DENIED", "no_authority")
        mark = K.governance_mark("act", emergency=a["emergency"], operation=a["operation"], args=a["args"])
        return Verdict("RUN", None, mark, None, {"subject": who, "obo": None, "op": a["operation"], "args": a["args"],
                                                 "emergency": True})

    def _end(self, who, a, seq, tick) -> Verdict:
        em = self.emergency_active(a["emergency"], seq, tick)
        if em is None:
            return _r("DENIED", "emergency_inactive")
        if not any(who in E.body_of(self.doc, b)["members"] for b in em["bodies"]):
            return _r("DENIED", None)  # frozen text names no refusal code for a non-member ending an emergency
        return Verdict("OK", None, K.governance_mark("end", emergency=a["emergency"]), K.ok_body("end", emergency=a["emergency"]))

    # -- static rules (parity with r3_shared.governance.validate_governance) --------------------------------
    def validate_doc(self, doc) -> list[str]:
        return static_errors(doc, self.base, self.ops)
