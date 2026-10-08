"""Oracle-backed reference for the H26 low channels (FakeHonest) with switchable mutants (KNOWN["H26"] names) and
extra fault flags for the known-negative tests. Test-only, never registered. Visibility comes from r3_oracle (the fake IS
the oracle; the test proves the HARNESS pipeline, not any variant)."""
from __future__ import annotations

import json

import copy
import hashlib

from r3_harness.h26.env import decision_rec
from r3_oracle import disclosure as D, disclosure_prov as P, disclosure_reads as R, ops_model
from r3_oracle.disclosure import Facts
from r3_shared.disclosure import marker, tool_schema
from r3_shared.variant import CallResult, ToolDescriptor
from r3_shared.world import diff as world_diff
from r3_shared.mutants import validate
from tests.fakes.fake_variant import FakeDeployment


def _res(t):
    return CallResult(t[0], t[1])


class H26Deployment(FakeDeployment):
    flags: frozenset = frozenset()
    mutants: frozenset = frozenset()

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.facts = Facts()
        self.subs: dict = {}
        self.nsub = 0
        self._n = 0

    # -- helpers ------------------------------------------------------------------------------------------------
    def _snap(self):
        objs, links = {}, []
        for t in self.known_types:
            for o in self.world.list(t):
                objs[f"{t}:{o['key']}"] = {"props": o["props"], "version": o["version"]}
        for lt in self.ops_spec["link_types"]:
            links += [[lt["name"], s, d] for s, d in self.world.links(lt["name"])]
        return {"objects": objs, "links": links, "effects": self.world.external_effects()}

    def _lv(self, sub):
        return D.low_view(self._snap(), self.auth_spec, sub, self.ops_spec, self.facts)

    def _rid(self, kind):
        self._n += 1
        return f"{kind}-{hashlib.sha256(str(self._n).encode()).hexdigest()[:8]}"

    # -- surfaces -----------------------------------------------------------------------------------------------
    def tools(self, token):
        sub = self._sub(token)
        if sub is None:
            return []
        if "hidden_tool_schema" in self.mutants:
            return [ToolDescriptor(o["name"], tool_schema(o)) for o in self.ops_spec["operations"]]
        edges = self.g2["edges"]
        return [ToolDescriptor(r["name"], r["input_schema"]) for r in R.expected_tools(self.auth_spec, self.ops_spec, sub, edges)]

    def call_tool(self, token, name, args, on_behalf_of=None, request_id=None):
        if name not in {t.name for t in self.tools(token)}:
            sub = self._sub(token)
            if not sub:
                return CallResult("DENIED", {"reason": "token"})
            res = CallResult("INVALID", {"reason": "unknown_tool"})
            out = ops_model.evaluate(self.ops_spec, self.auth_spec, sub, on_behalf_of, name, args, self._snap(),
                                     self.clock.now(), frozenset(self.g2["used"]), request_id)
            self._gov_record(sub, name, args, request_id or self._rid("r"), on_behalf_of, out, res)  # H27 convention
            return res
        return self.direct(token, name, args, on_behalf_of, request_id)

    def direct(self, token, operation, args, on_behalf_of=None, request_id=None):
        res = self._direct(token, operation, args, on_behalf_of, request_id)
        return res

    def _gov_record(self, sub, operation, args, rid, obo, out, res):
        k = out.kind
        if res.status in ("OK", "DENIED", "INVALID") and (k in (ops_model.COMMIT, ops_model.DENIED_AUTHORITY, ops_model.DENIED_RULE,
                                                              ops_model.NEEDS_APPROVAL) or (k == ops_model.INVALID and out.detail.startswith("precondition"))) \
                and res.status != "OK":
            self.facts.decisions.append(decision_rec(self.ops_spec, sub, obo, operation, args, rid, res.status,
                                                     res.body.get("reason", ""), [], [], self._head(), self.clock.now()))

    def _direct(self, token, operation, args, on_behalf_of=None, request_id=None):
        with self._lock:
            if self.crashed:
                return CallResult("UNAVAILABLE", {"reason": "crashed"})
            sub = self._sub(token)
            if sub is None:
                return CallResult("DENIED", {"reason": "token"})
            before = self._snap()
            out = ops_model.evaluate(self.ops_spec, self.auth_spec, sub, on_behalf_of, operation, args, before,
                                     self.clock.now(), frozenset(self.g2["used"]), request_id)
            rid = request_id or self._rid("r")
            if "deny_all" in self.flags:
                return CallResult("DENIED", {"reason": "authority"})
            k = out.kind
            if k == ops_model.DENIED_AUTHORITY:
                res = self._refuse(sub, operation, args, before)
            elif k == ops_model.UNKNOWN_OP:
                return CallResult("INVALID", {"reason": "unknown_operation"})
            elif k == ops_model.INVALID:
                res = CallResult("INVALID", {"reason": "schema" if not out.detail.startswith("precondition") else "precondition"})
            elif k in (ops_model.DENIED_RULE, ops_model.NEEDS_APPROVAL):
                res = CallResult("DENIED", {"reason": "rule" if k == ops_model.DENIED_RULE else "approval_required"})
            else:
                return self._commit_effects(sub, operation, args, rid, out, on_behalf_of)
            self._gov_record(sub, operation, args, rid, on_behalf_of, out, res)
            return res

    def _refuse(self, sub, operation, args, snap):
        body = {"reason": "authority"}
        opd = ops_model.op_of(self.ops_spec, operation)
        refs = [f"{t}:{k}" for t, k in ops_model.resources_of(opd, args)] if opd else []
        if "existence_status_split" in self.mutants:  # 403 vs 404
            if not all(r in snap["objects"] for r in refs):
                return CallResult("INVALID", {"reason": "not_found"})
            body = {"reason": "forbidden"}
        if "error_detail_leak" in self.mutants and refs and refs[0] in snap["objects"]:
            body["detail"] = f"{refs[0]} {snap['objects'][refs[0]]['props']}"
        return CallResult("DENIED", body)

    def _commit_effects(self, sub, operation, args, rid, out, obo):
        head0 = self.world._con.execute("SELECT COALESCE(MAX(seq),0) FROM world_log").fetchone()[0]
        before = self._snap()
        with self.world.transaction(tag="effect") as tx:
            for e in out.effects:
                kd = e["kind"]
                if kd == "create":
                    t, k = e["ref"].split(":", 1)
                    self.world.create(t, k, e["props"])
                elif kd == "update":
                    t, k = e["ref"].split(":", 1)
                    self.world.update(t, k, {f: v[1] for f, v in e["changes"].items()})
                elif kd == "link":
                    self.world.link(*e["ref"].split("|", 2))
                elif kd == "unlink":
                    self.world.unlink(*e["ref"].split("|", 2))
                elif kd == "external":
                    self.world.external_write(e["adapter"], e["target"], e["payload"], rid)
            tx.mark("commit", {"request_id": rid, "kind": "direct", "authority_version": self.authority_version()})
        self.g2["used"][rid] = {"authority_version": self.authority_version(), "world_seq": 0, "tick": tx.tick, "path": [],
                                "on_behalf_of": obo}
        rows = self.world._con.execute("SELECT seq,tx,tag,tick,writer,kind,ref,data_json FROM world_log WHERE seq>? ORDER BY seq",
                                       (head0,)).fetchall()
        rws = [{"seq": r[0], "tx": r[1], "tag": r[2], "tick": r[3], "writer": r[4], "kind": r[5], "ref": r[6],
                "data": json.loads(r[7])} for r in rows]
        head = rws[-1]["seq"] if rws else head0
        eff = world_diff(before, self._snap())
        self.facts.decisions.append(decision_rec(self.ops_spec, sub, obo, operation, args, rid, "OK", "ok", eff, rws, head, tx.tick))
        return CallResult("OK", {})

    # -- hidden parents / edges / cases answer exactly like absent ones (PROT-H26 3.1) --------------------------
    def delegate(self, token, edge, request_id):
        sub = self._sub(token)
        em = {e["id"]: e for e in self.g2["edges"]}
        if sub and isinstance(edge, dict) and edge.get("parent") in em and "edge_hidden_ok" not in self.flags \
                and not P.edge_visible(em, edge["parent"], sub):
            return CallResult("INVALID", {"reason": "unknown_parent"})
        return super().delegate(token, edge, request_id)

    def revoke(self, token, edge_id, request_id):
        sub = self._sub(token)
        em = {e["id"]: e for e in self.g2["edges"]}
        if sub and edge_id in em and "edge_hidden_ok" not in self.flags and not P.edge_visible(em, edge_id, sub):
            return CallResult("INVALID", {"reason": "unknown_edge"})
        return super().revoke(token, edge_id, request_id)

    def constitutional(self, token, action, request_id):
        sub = self._sub(token)
        c = self.g3["cases"].get(action.get("case")) if isinstance(action, dict) else None
        if sub and c is not None and action.get("kind") != "propose" and sub != c["requester"] and not self._member(sub):
            return CallResult("INVALID", {"reason": "unknown_case"})
        return super().constitutional(token, action, request_id)

    def _member(self, sub):
        return any(sub in b["members"] for b in (self.governance or {"bodies": []})["bodies"])

    # -- low channels -------------------------------------------------------------------------------------------
    def _low(self, token):
        sub = self._sub(token)
        return None if sub is None else self._lv(sub)

    def read_object(self, token, ref):
        lv = self._low(token)
        if lv is None or not isinstance(ref, str):
            return CallResult("INVALID", {"reason": "not_found"})
        if "existence_status_split" in self.mutants and ref not in lv.objects and ref in self._snap()["objects"]:
            return CallResult("DENIED", {"reason": "forbidden"})
        return _res(R.expected_read_object(lv, ref))

    def list_objects(self, token, type_):
        lv = self._low(token)
        if not isinstance(type_, str):
            return CallResult("INVALID", {"reason": "unknown_type"})
        return CallResult("INVALID", {"reason": "unknown_type"}) if lv is None else _res(R.expected_list_objects(lv, type_))

    def list_links(self, token, ref, link_type):
        lv = self._low(token)
        if not (isinstance(ref, str) and isinstance(link_type, str)):
            return CallResult("OK", {"out": [], "in": []})
        return CallResult("OK", {"out": [], "in": []}) if lv is None else _res(R.expected_list_links(lv, ref, link_type))

    def query(self, token, name, args):
        lv = self._low(token)
        r = None if lv is None else R.expected_query(lv, name, args)
        return CallResult("OK", {"value": None}) if r is None else _res(r)

    def prov_decision(self, token, decision_id):
        lv = self._low(token)
        if lv is None:
            return CallResult("INVALID", {"reason": "unknown_decision"})
        if {"provenance_edge_retained", "redaction_fabrication"} & self.mutants:
            d = P.find_decision(lv, decision_id)
            if d is None or not P.decision_low(lv, d):
                return CallResult("INVALID", {"reason": "unknown_decision"})
            v = dict(d["scalars"])
            if "provenance_edge_retained" in self.mutants:
                v["authority_path"] = list(d["edge_path"])
                return CallResult("OK", {"partial": True, "decision": v})
            exp = P.expected_decision(lv, d)
            v = {k: ("system" if (k in ("subject", "on_behalf_of") and x == marker("actor")) else x) for k, x in exp.items()}
            return CallResult("OK", {"partial": True, "decision": v})
        if "digest_leak" in self.flags:
            d = P.find_decision(lv, decision_id)
            r = P.expected_prov_decision(lv, decision_id)
            if d is not None and r[0] == "OK":
                r[1]["decision"]["effect_digest"] = d["scalars"]["effect_digest"]
            return _res(r)
        return _res(P.expected_prov_decision(lv, decision_id))

    def prov_object(self, token, ref):
        lv = self._low(token)
        return CallResult("OK", {"partial": True, "decisions": []}) if lv is None else _res(P.expected_prov_object(lv, ref))

    def authority_used_as(self, token, request_id):
        lv = self._low(token)
        return CallResult("INVALID", {"reason": "unknown_decision"}) if lv is None else _res(P.expected_authority_used_as(lv, request_id))

    # -- subscriptions -----------------------------------------------------------------------------------------
    def subscribe(self, token, spec):
        sub = self._sub(token)
        if sub is None:
            return CallResult("INVALID", {"reason": "schema"})
        self.nsub += 1
        sid = f"sub-{self.nsub}"
        if "uuid_ids" in self.flags:  # known-negative: nondeterministic ids (A/A must catch it)
            import uuid
            sid = f"sub-{uuid.uuid4().hex[:8]}"
        snap = self._snap()
        self.subs[sid] = {"sub": sub, "types": list(spec.get("types", [])), "snap": snap, "head": self._head()}
        return CallResult("OK", {"sub": sid})

    def _head(self):
        return self.world._con.execute("SELECT COALESCE(MAX(seq),0) FROM world_log").fetchone()[0]

    def poll(self, token, sub):
        s = self.subs.get(sub)
        if s is None or self._sub(token) != s["sub"]:
            return CallResult("INVALID", {"reason": "unknown_subscription"})
        now = self._snap()
        evs = []
        unf = "subscription_unfiltered" in self.mutants
        a, b = s["snap"], now
        head = self._head()
        lva = D.low_view(a, self.auth_spec, s["sub"], self.ops_spec, self.facts)
        lvb = D.low_view(b, self.auth_spec, s["sub"], self.ops_spec, self.facts)
        oa, ob = (a["objects"], b["objects"]) if unf else (lva.objects, lvb.objects)
        oa = {r: (v["props"] if unf else v) for r, v in oa.items()}
        ob = {r: (v["props"] if unf else v) for r, v in ob.items()}
        tick = self.clock.now()
        for ref in sorted(set(oa) | set(ob)):
            if ref.split(":", 1)[0] not in s["types"] or oa.get(ref) == ob.get(ref):
                continue
            kind = "create" if ref not in oa else "delete" if ref not in ob else "update"
            props = {} if kind == "delete" else (ob[ref] if kind == "create" else {k: v for k, v in ob[ref].items() if oa[ref].get(k) != v})
            evs.append({"seq": head, "tick": tick, "kind": kind, "ref": ref, "props": props})
        la = {tuple(x) for x in (a["links"] if unf else lva.links)}
        lb = {tuple(x) for x in (b["links"] if unf else lvb.links)}
        for kind, ls in (("link", sorted(lb - la)), ("unlink", sorted(la - lb))):
            evs += [{"seq": head, "tick": tick, "kind": kind, "link": list(x), "props": {}} for x in ls
                    if x[1].split(":", 1)[0] in s["types"] or x[2].split(":", 1)[0] in s["types"]]
        s["snap"] = copy.deepcopy(now)
        return CallResult("OK", {"events": evs})


class H26Variant:
    name = "fake-h26"
    audience = "fake"
    deployment_class = H26Deployment

    def __init__(self, mutants=(), flags=()):
        self.mutants = validate(mutants)
        self.flags = frozenset(flags)

    def deploy(self, domain, world_handle_factory, verifier, ops_spec, auth_spec, clock, state_dir=None, history=None,
               anchor=None, governance=None):
        cls = type("Dep", (self.deployment_class,), {"mutants": self.mutants, "flags": self.flags})
        writer = sorted(w for a in auth_spec["service_accounts"] for w in a["world_writers"])[0]
        return cls(domain, lambda _w: world_handle_factory(writer), verifier, clock, auth_spec, state_dir, history, anchor, governance, ops_spec)


FAKES = {"fake-honest": {}, "fake-denyall": {"flags": ("deny_all",)}, "fake-digestleak": {"flags": ("digest_leak",)},
         "fake-uuid": {"flags": ("uuid_ids",)}}


def load(name: str, mutants=()):
    """Test-variant loader for scripts/run_h26.py --test-variants (never registered). Mutant fakes: fake-<mutant>."""
    kw = FAKES.get(name)
    if kw is None and name.startswith("fake-") and name[5:] in __import__("r3_shared.mutants", fromlist=["ALL"]).ALL:
        return H26Variant((name[5:],) + tuple(mutants))
    if kw is None:
        raise KeyError(name)
    return H26Variant(mutants, kw.get("flags", ()))
