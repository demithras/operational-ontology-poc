"""Reference behaviour for the Gate 3 Deployment methods (fakes only; never registered). Honest about FORMS and the
protocol (check order token -> schema -> no_governance -> case lookups, one governance mark per OK, idempotent
request_id) but allow-all for visibility and WITHOUT the PROT-H25 s2 evaluator (that is the oracle's job)."""
from __future__ import annotations

from r3_shared.constitutional import check_action, governance_mark, ok_body, refusal_body
from r3_shared.disclosure import marker
from r3_shared.governance import validate_governance
from r3_shared.variant import CallResult


def _r(status, reason):
    return CallResult(status, refusal_body(reason))


class G3Mixin:
    def _g3_init(self, governance):
        self.governance = governance
        self.g3 = {"cases": {}, "emerg": {}, "results": {}, "subs": {}, "n": 0}

    def set_governance(self, doc):
        ops = getattr(self, "ops_spec", None)
        if ops and self.auth_spec.get("principals"):
            validate_governance(doc, self.auth_spec, ops)
        self.governance = doc

    def case_state(self, case_id):
        c = self.g3["cases"].get(case_id)
        return None if c is None else dict(c)

    def _g3_commit(self, sub, rid, payload, ok):
        armed, self._armed = self._armed, None
        if armed == "before_commit":
            self.crashed = True
            return CallResult("UNKNOWN", {"reason": "crashed"})
        with self.world.transaction(tag="governance") as tx:
            tx.mark("governance", payload)
            tx.mark("commit", {"request_id": rid, "kind": "constitutional", "authority_version": self.authority_version()})
        self.g3["results"][rid] = ok
        if armed == "after_commit":
            self.crashed = True
            return CallResult("UNKNOWN", {"reason": "crashed"})
        return CallResult("OK", ok)

    def constitutional(self, token, action, request_id):
        with self._lock:
            if self.crashed:
                return CallResult("UNAVAILABLE", {"reason": "crashed"})
            sub = self._sub(token)
            if sub is None:
                return _r("DENIED", "token")
            if check_action(action) is not None:
                return _r("INVALID", "schema")
            if self.governance is None:
                return _r("INVALID", "no_governance")
            if request_id in self.g3["results"]:
                return CallResult("OK", self.g3["results"][request_id])
            k, cs = action["kind"], self.g3["cases"]
            if k == "propose":
                if action["case"] in cs:
                    return _r("INVALID", "duplicate_case")
                bodies = sorted(b["id"] for b in self.governance["bodies"])[:1]
                cs[action["case"]] = {"case": action["case"], "requester": sub, "operation": action["operation"],
                                      "args": action["args"], "stage_outcomes": {}, "final": None, "executed": False,
                                      "_j": []}
                mark = governance_mark("propose", case=action["case"], requester=sub, on_behalf_of=action["on_behalf_of"],
                                       operation=action["operation"], args=action["args"], bodies=bodies)
                return self._g3_commit(sub, request_id, mark, ok_body("propose", case=action["case"], bodies=bodies))
            if k in ("judge", "appeal", "execute"):
                c = cs.get(action["case"])
                if c is None:
                    return _r("INVALID", "unknown_case")
                if k == "judge":
                    if any(j[:2] == (sub, action["stage"]) for j in c["_j"]):
                        return _r("INVALID", "already_judged")
                    c["_j"].append((sub, action["stage"], request_id))
                    mark = governance_mark("judge", case=action["case"], stage=action["stage"], judge=sub,
                                           value=action["value"], merit=action["merit"])
                    return self._g3_commit(sub, request_id, mark, ok_body("judge", case=action["case"], stage=action["stage"]))
                if k == "appeal":
                    mark = governance_mark("appeal", case=action["case"], by=sub)
                    return self._g3_commit(sub, request_id, mark, ok_body("appeal", case=action["case"]))
                if sub != c["requester"]:
                    return _r("DENIED", "not_requester")
                if not c["_j"]:
                    return _r("DENIED", "oracle_needed")
                c["executed"] = True
                mark = governance_mark("execute", case=action["case"], rule="decision", basis=[j[2] for j in c["_j"]])
                return self._g3_commit(sub, request_id, mark, {})
            e = self.g3["emerg"]
            if k == "act":
                if action["emergency"] not in e:
                    return _r("DENIED", "emergency_inactive")
                mark = governance_mark("act", emergency=action["emergency"], operation=action["operation"], args=action["args"])
                return self._g3_commit(sub, request_id, mark, {})
            e.pop(action["emergency"], None)
            return self._g3_commit(sub, request_id, governance_mark("end", emergency=action["emergency"]),
                                   ok_body("end", emergency=action["emergency"]))

    # ---- low channels: allow-all reference ---------------------------------------------------------------
    def read_object(self, token, ref):
        if not self._sub(token) or ":" not in ref:
            return _r_low("INVALID", "not_found")
        t, k = ref.split(":", 1)
        rec = self.world.get(t, k)
        return CallResult("OK", {"ref": ref, "props": rec["props"]}) if rec else _r_low("INVALID", "not_found")

    def list_objects(self, token, type_):
        if not getattr(self, "known_types", None) or type_ not in self.known_types:
            return _r_low("INVALID", "unknown_type")
        return CallResult("OK", {"refs": sorted(f"{type_}:{o['key']}" for o in self.world.list(type_))})

    def list_links(self, token, ref, link_type):
        out = sorted(d for _, d in self.world.links(link_type, src=ref))
        inn = sorted(s for s, _ in self.world.links(link_type, dst=ref))
        return CallResult("OK", {"out": out, "in": inn})

    def query(self, token, name, args):
        if name == "count" and "type" in args:
            return CallResult("OK", {"value": len(self.world.list(args["type"]))})
        return CallResult("OK", {"value": None})

    def subscribe(self, token, spec):
        self.g3["n"] += 1
        sid = f"sub-{self.g3['n']}"
        self.g3["subs"][sid] = {"types": list(spec["types"]), "seen": self._snap(spec["types"])}
        return CallResult("OK", {"sub": sid})

    def _snap(self, types):
        return {f"{t}:{o['key']}": o["props"] for t in types for o in self.world.list(t)}

    def poll(self, token, sub):
        s = self.g3["subs"][sub]
        now, evs = self._snap(s["types"]), []
        for ref in sorted(set(now) | set(s["seen"])):
            a, b = s["seen"].get(ref), now.get(ref)
            if a == b:
                continue
            kind = "create" if a is None else "delete" if b is None else "update"
            props = b or {} if kind != "update" else {k: v for k, v in b.items() if a.get(k) != v}
            self.g3["n"] += 1
            evs.append({"seq": self.g3["n"], "tick": self.clock.now(), "kind": kind, "ref": ref, "props": props})
        s["seen"] = now
        return CallResult("OK", {"events": evs})

    def prov_decision(self, token, decision_id):
        u = self.g2["used"].get(decision_id)
        if u is None:
            return _r_low("INVALID", "unknown_decision")
        d = {"decision_id": decision_id, "kind": "direct", "subject": marker("actor"), "on_behalf_of": u["on_behalf_of"],
             "operation": "put", "args_digest": marker("digest"), "status": "OK", "reason": "", "effect_digest": marker("digest"),
             "world_seq": u["world_seq"], "tick": u["tick"], "authority_path": list(u["path"])}
        return CallResult("OK", {"partial": True, "decision": d})

    def prov_object(self, token, ref):
        return CallResult("OK", {"partial": True, "decisions": []})

    def authority_used_as(self, token, request_id):
        u = self.g2["used"].get(request_id)
        if u is None:
            return _r_low("INVALID", "unknown_decision")
        return CallResult("OK", {"partial": True, "on_behalf_of": u["on_behalf_of"], "path": list(u["path"]),
                                 "authority_version": marker("digest"), "world_seq": u["world_seq"], "tick": u["tick"]})


def _r_low(status, reason):
    return CallResult(status, {"reason": reason})
