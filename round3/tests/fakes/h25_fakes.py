"""Test-only H25 fakes (never registered). FakeHonest is a reference deployment OVER THE ORACLE: correct by construction, it
exists to prove the harness can say SUPPORTED. Each known-negative fake runs a SOURCE-MUTATED CLONE of the oracle
(r3_oracle.const_eval / constitution text with one edit, loaded as private modules so the harness's own judge is never
affected). `load(name)` builds a Variant. Names: fake-honest, fake-quorumweak, fake-autofill, fake-noexpiry,
fake-precinverted, fake-domainbranch, fake-meritreader, fake-ignoresjudgments, fake-alwaysoracleneeded."""
from __future__ import annotations

import copy
import json
import types
from pathlib import Path

from r3_oracle import const_eval, const_judge
from r3_oracle import constitution as cons_mod
from r3_oracle import ops_model
from r3_oracle.authority_v2 import INF as _INF
from r3_oracle.constitution import Constitution, to_v2
from r3_shared import constitutional as K
from r3_shared.governance import validate_governance
from r3_shared.variant import CallResult
from tests.fakes.h24_fakes import H24Dep, _Abort

BIG = 10 ** 9
REPL = {
    "quorumweak": ([('return ALLOW if yes >= k else', 'return ALLOW if yes >= max(1, k - 1) else')], []),
    "autofill": ([('    if d["outcome"] == AWAIT:\n        return res\n',
                   '    if d["outcome"] == AWAIT:\n        return {**res, "state": "FINAL", "outcome": ALLOW, "rule": "decision", '
                   '"basis": ["synth-judgment"]}\n')], []),
    "noexpiry": ([], [('if tick >= em["expires_at"]:', 'if False:')]),
    "precinverted": ([('top = max(body_of', 'top = min(body_of'),
                      ('not any(d in _above(doc, c) for d in cand)', 'not any(c in _above(doc, d) for d in cand)'),
                      ('_strict_sub(o, s) for d in cand', '_strict_sub(s, o) for d in cand')], []),
    "domainbranch": ([], [('        if c["executed"] is not None:\n            return Verdict("OK_STORED", None)\n',
                           '        if c["executed"] is not None:\n            return Verdict("OK_STORED", None)\n'
                           '        if self.doc["domain"] == "project" and c["requester"].endswith("-1"):\n'
                           '            return Verdict("RUN", None, K.governance_mark("execute", case=a["case"], rule="decision", '
                           'basis=[]), None, {"subject": c["requester"], "obo": c["obo"], "op": c["operation"], '
                           '"args": c["args"], "emergency": False})\n')]),
    "meritreader": ([], [('"value": a["value"], "rid": ev["rid"]}',
                          '"value": ("concur" if "approve" in a["merit"] and a["stage"] == "decision" else a["value"]), '
                          '"rid": ev["rid"]}')]),
    "ignoresjudgments": ([('    yes = sum(j["value"] == YES[stage] for j in cnt)',
                           '    if cnt:\n        return ALLOW\n    yes = sum(j["value"] == YES[stage] for j in cnt)')], []),
    "alwaysoracleneeded": ([], []),  # quirk of H25Dep: refuses every execute/act the oracle would commit
    "honest": ([], []),
}


def _sub(src: str, repl: list) -> str:
    for old, new in repl:
        assert old in src, f"mutation anchor missing: {old[:50]!r}"
        src = src.replace(old, new, 1)
    return src


def mutated_constitution(name: str):
    """-> (Constitution class, mutated source of the decision modules) for fake `name`."""
    re_, rc = REPL[name]
    src_e = _sub(Path(const_eval.__file__).read_text(), re_)
    src_c = _sub(Path(cons_mod.__file__).read_text(), rc).replace("from . import authority, const_eval as E, ops_model",
                                                                  "from . import authority, ops_model")
    e = types.ModuleType("r3_oracle._mut_eval")
    e.__package__ = "r3_oracle"
    exec(compile(src_e, f"<mut-eval-{name}>", "exec"), e.__dict__)
    c = types.ModuleType("r3_oracle._mut_cons")
    c.__package__ = "r3_oracle"
    c.E = e
    exec(compile(src_c, f"<mut-cons-{name}>", "exec"), c.__dict__)
    return c.Constitution, {"const_eval.py": src_e, "constitution.py": src_c}


class H25Dep(H24Dep):
    def __init__(self, domain, factory, verifier, ops, auth, clock, mutants=frozenset(), state_dir=None, governance=None,
                 cons=Constitution, quirk=None):
        super().__init__(domain, factory, verifier, ops, to_v2(auth), clock, mutants, state_dir)
        self.auth_v3, self.gov0, self.cons, self.quirk = copy.deepcopy(auth), copy.deepcopy(governance), cons, quirk
        self.C = cons.from_docs(auth, governance, ops)
        self.g3 = {"results": {}, "events": []}
        self._load_g3()

    def _g3_file(self):
        return Path(self.state_dir) / "g3.json" if self.state_dir else None

    def _save_g3(self):
        p = self._g3_file()
        if p is not None:
            p.write_text(json.dumps(self.g3))

    def _load_g3(self):
        p = self._g3_file()
        self.g3 = json.loads(p.read_text()) if p is not None and p.exists() else {"results": {}, "events": []}
        self.C = self.cons.from_docs(self.auth_v3, self.gov0, self.ops)
        for ev in self.g3["events"]:
            self.C = self.C.apply(ev)

    def restart(self):
        super().restart()
        self._load_g3()

    def _commit_event(self, ev):
        self.C = self.C.apply(ev)
        self.g3["events"].append(ev)

    # -- governed ordinary requests ------------------------------------------------------------------------
    def _run_locked(self, token, op, args, obo, rid, backstop):
        sub = self._sub(token)
        if sub is not None and self.C.doc is not None and isinstance(args, dict):
            from r3_oracle import const_eval as E
            if E.covering(self.C.doc, op, E.resources_for(self.ops, op, args)):
                return CallResult("DENIED", {"reason": "case_required"})
        return super()._run_locked(token, op, args, obo, rid, backstop)

    # -- PROT-H25 s3 ---------------------------------------------------------------------------------------
    def constitutional(self, token, action, request_id):
        with self._lock:
            if self.crashed:
                return CallResult("UNAVAILABLE", {"reason": "crashed"})
            sub = self._sub(token)
            if sub is not None and request_id in self.g3["results"]:
                return CallResult("OK", self.g3["results"][request_id])
            armed, self._armed = self._armed, None
            try:
                with self.world.transaction(tag="governance") as tx:
                    v = self.C.decide_action(sub, action, BIG, tx.tick)
                    if v.status == "OK_STORED":
                        raise _Abort(CallResult("OK", {}))
                    if v.status not in ("OK", "RUN"):
                        raise _Abort(CallResult(v.status if v.status in ("DENIED", "INVALID") else "INVALID",
                                                {"reason": v.reason or "not_party"}))
                    out = None
                    if v.status == "RUN":
                        out = const_judge.op_outcome(self.C, v.run, self.world_snapshot(), tx.tick, False)
                        if out.kind != ops_model.COMMIT:
                            st = "INVALID" if out.kind in (ops_model.INVALID, ops_model.UNKNOWN_OP) else "DENIED"
                            raise _Abort(CallResult(st, {"reason": "approval_required" if out.kind == ops_model.NEEDS_APPROVAL
                                                         else out.detail}))
                    if out is not None and self.quirk == "alwaysoracleneeded":
                        raise _Abort(CallResult("DENIED", {"reason": "oracle_needed"}))
                    if armed == "before_commit":
                        self.crashed = True
                        raise _Abort(CallResult("UNKNOWN", {"reason": "crashed"}))
                    if out is not None:
                        self._apply_in_tx(out.effects)
                    seq = tx.mark("governance", v.mark)
                    if out is not None:
                        tx.mark("commit", {"request_id": request_id, "kind": "constitutional",
                                           "authority_version": self.ra.digest_at(None)})
                    tick = tx.tick
            except _Abort as ab:
                return ab.result
            self._commit_event({"kind": "action", "subject": sub, "action": action, "seq": seq, "tick": tick,
                                "rid": request_id})
            body = v.body if v.body is not None else {"op": action.get("operation")}
            self.g3["results"][request_id] = body
            self._save_g3()
            if armed == "after_commit":
                self.crashed = True
                return CallResult("UNKNOWN", {"reason": "crashed"})
            return CallResult("OK", body)

    def set_governance(self, doc):
        with self._lock:
            validate_governance(doc, self.C.base, self.ops)
            with self.world.transaction(tag="governance") as tx:
                seq = tx.mark("governance", K.governance_mark("set_governance", doc=doc))
                tick = tx.tick
            self._commit_event({"kind": "set_governance", "doc": doc, "seq": seq, "tick": tick})
            self._save_g3()

    def set_authority(self, spec):
        super().set_authority(spec)
        ev = self.ra.events[-1]
        self._commit_event({"kind": "authority", "op": "set_authority", "payload": {"spec": spec}, "seq": ev.seq,
                            "tick": ev.tick})
        self._save_g3()

    def case_state(self, case_id):
        c = self.C.case(case_id)
        return None if c is None else {"case": case_id, "requester": c["requester"], "executed": c["executed"] is not None}


class H25Variant:
    audience = "fake"

    def __init__(self, name="fake-honest"):
        self.name = name
        key = name.split("fake-", 1)[1]
        self.cons, self.sources = mutated_constitution(key)
        self.quirk = key if key == "alwaysoracleneeded" else None

    def deploy(self, domain, factory, verifier, ops_spec, auth_spec, clock, state_dir=None, history=None, anchor=None,
               governance=None):
        return H25Dep(domain, factory, verifier, ops_spec, auth_spec, clock, frozenset(), state_dir, governance, self.cons, self.quirk)


NAMES = tuple("fake-" + k for k in REPL)


def load(name, mutants=()):
    return H25Variant(name)


_ = _INF
