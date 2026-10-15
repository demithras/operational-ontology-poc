"""Knowledge sovereignty, part 2: the low CHANNELS (PROT-H26 s3, P1e-5): read_object / list_objects / list_links / query /
tools / subscribe / poll. Each answers ONLY from the observer's low view (paladin.sovview); a hidden object is answered exactly
as an absent one (one code path: `view.objects.get(ref) is None`). Mixed into `paladin.core.Core`; the deployment calls these
under the Core lock with the subject verified from the token.

Mutants (constructor-activated) sit at the real sites: existence_status_split (read layer), hidden_tool_schema (tools),
subscription_unfiltered (poll).
"""
from __future__ import annotations

import json

from paladin.engine import InvalidRequest
from paladin.engine.state import State
from paladin.sovview import LowView, implied_refs, low_view, split
from r3_shared.authspec import allowed_operations, effective_disclosure
from r3_shared.disclosure import tool_schema
from r3_shared.variant import CallResult, ToolDescriptor

NOT_FOUND = CallResult("INVALID", {"reason": "not_found"})


class SovMixin:
    # ---- the observer's low view ---------------------------------------------------------------------------
    def principal_doc(self, sub: str) -> dict | None:
        return next((p for p in self.auth["principals"] if p["id"] == sub), None)

    def world_snapshot(self) -> tuple:
        objs, links = {}, set()
        for t in self.type_names:
            for row in self._svc.list(t):
                objs[f"{t}:{row['key']}"] = row["props"]
        for lt in self.link_names:
            links |= {(lt, a, b) for a, b in self._svc.links(lt)}
        return objs, links

    def live_scopes(self, sub: str, tick: int) -> list:
        """(scope, root principal | None) of the live edges `sub` holds and the ACTIVE emergencies it is a grantee of."""
        out, by_id = [], {p["id"]: p for p in self.auth["principals"]}
        rev, caps = set(self.auth.get("revoked", ())), {e["id"]: e for e in self.auth.get("capabilities", ())}
        for e in caps.values():
            if e["child"] != sub:
                continue
            path, cur = [], e
            while cur is not None:
                path.append(cur)
                cur = caps.get(cur["parent"])
            if any(x["id"] in rev or (x["expires_at"] is not None and tick >= x["expires_at"]) for x in path):
                continue
            out.append((e["scope"], by_id.get(path[-1]["issuer"])))
        if self.book is not None:
            for cid in self.book.order:
                c = self.book.cases[cid]
                if c.op == "emergency:declare" and isinstance(c.args, dict) and sub in c.args.get("grantees", ()) \
                        and self.book.emergency(c.args["emergency"], tick) is c and tick < c.args["expires_at"]:
                    out.append((c.args["scope"], None))
        return out

    def view_for(self, sub: str, snap: tuple | None = None) -> LowView:
        obs = self.principal_doc(sub)
        objs, links = snap if snap is not None else self.world_snapshot()
        imp = implied_refs(self.ops_spec, self.auth, obs, objs, self.live_scopes(sub, self.clock.now()))
        return low_view(effective_disclosure(self.auth, self.ops_spec), obs, objs, links, imp)

    # ---- reads -------------------------------------------------------------------------------------------------
    def read_object(self, sub: str, ref) -> CallResult:
        view = self.view_for(sub)
        props = view.objects.get(ref) if isinstance(ref, str) else None
        if props is None:
            if "existence_status_split" in self.mutants and isinstance(ref, str) and ref in self.world_snapshot()[0]:
                return CallResult("DENIED", {"reason": "forbidden"})   # MUTANT: the 403-vs-404 split in the read layer
            return NOT_FOUND
        return CallResult("OK", {"ref": ref, "props": json.loads(json.dumps(props))})

    def list_objects(self, sub: str, type_) -> CallResult:
        if not isinstance(type_, str) or type_ not in self.type_names:
            return CallResult("INVALID", {"reason": "unknown_type"})
        return CallResult("OK", {"refs": sorted(r for r in self.view_for(sub).objects if split(r)[0] == type_)})

    def list_links(self, sub: str, ref, link_type) -> CallResult:
        view = self.view_for(sub)
        if not isinstance(ref, str) or ref not in view.objects:
            return CallResult("OK", {"out": [], "in": []})   # G3-E19: absent == hidden == empty
        return CallResult("OK", {"out": sorted(b for lt, a, b in view.links if lt == link_type and a == ref),
                                 "in": sorted(a for lt, a, b in view.links if lt == link_type and b == ref)})

    def query(self, sub: str, name, args) -> CallResult:
        """PROT-H26 s3.3: the read function evaluated over the observer's low view as the world."""
        from paladin.core import plain  # noqa: PLC0415
        if not isinstance(name, str) or name not in self.reads or not isinstance(args, dict):
            return CallResult("INVALID", {"reason": "unknown_query"})
        view = self.view_for(sub)
        objects = {split(r): {"props": dict(p), "ver": 1} for r, p in view.objects.items()}
        links = {(lt, split(a), split(b)): {"props": {}, "ver": 1} for lt, a, b in view.links}
        rd = next((r for r in self.ops_spec["reads"] if r["name"] == name), None)
        for i in (rd["inputs"] if rd else ()):   # G3-E20/E19: an absent (== hidden) resource key answers as an object with no facts
            v = args.get(i["name"])
            if i["type"] == "resource" and isinstance(v, str) and v.strip() != "" and (i["resource_type"], v) not in objects:
                objects[(i["resource_type"], v)] = {"props": {}, "ver": 1}
        self.eng.store.current = State(self.eng.model, objects, links)
        try:
            return CallResult("OK", {"value": plain(self.eng.call_function(name, json.loads(json.dumps(args)), principal=sub))})
        except InvalidRequest:
            return CallResult("INVALID", {"reason": "invalid_args"})
        # no catch-all: a hidden field degrades inside the read function like a null (PROT-H26 s3.3); any other exception is a
        # variant defect and propagates (the harness records variant_error) - never a guessed constant answer.

    def leak_detail(self, op, args) -> dict:
        """MUTANT error_detail_leak only: the failing request's object values (what a raw exception/rule detail would carry)."""
        objs, _l = self.world_snapshot()
        return {r: objs.get(r) for r in (f"{t}:{k}" for t, k in self.refs_of(op, args))}

    # ---- tools (R26-4) -------------------------------------------------------------------------------------------
    def tool_names(self, sub: str, exposed: set) -> list:
        """The operations the subject (or its delegators / live edges / active emergencies) could be granted (PROT-H23 R3)."""
        names = set(exposed)
        for sc, root in self.live_scopes(sub, self.clock.now()):   # live edges (root must hold the op) and active emergencies
            names |= {o for o in sc["operations"] if o in self.ops and (root is None or o in allowed_operations(
                self.auth, root["id"], [o]))}
        if "hidden_tool_schema" in self.mutants:   # MUTANT: the full grant set, not the subject's
            names = set(self.ops)
        return sorted(names)

    def tool_descriptors(self, sub: str, exposed: set) -> list:
        return [ToolDescriptor(n, tool_schema(self.ops[n])) for n in self.tool_names(sub, exposed)]

    # ---- subscriptions (3.5) -------------------------------------------------------------------------------------
    def subscribe(self, sub: str, spec) -> CallResult:
        if not (isinstance(spec, dict) and set(spec) == {"types"} and isinstance(spec["types"], list)
                and all(isinstance(t, str) for t in spec["types"])):
            return CallResult("INVALID", {"reason": "schema"})
        if any(t not in self.type_names for t in spec["types"]):
            return CallResult("INVALID", {"reason": "unknown_type"})
        self._nsub += 1
        sid = f"sub-{self._nsub}"
        objs, links = self.world_snapshot()
        self.subs[sid] = {"who": sub, "types": set(spec["types"]), "seq": self._svc_head(), "objs": objs, "links": links}
        return CallResult("OK", {"sub": sid})

    def _svc_head(self) -> int:
        return int(self._svc._con.execute("SELECT COALESCE(MAX(seq),0) FROM world_log").fetchone()[0])

    def poll(self, sub: str, sid) -> CallResult:
        s = self.subs.get(sid) if isinstance(sid, str) else None
        if s is None or s["who"] != sub:
            return CallResult("INVALID", {"reason": "unknown_sub"})
        rows = self._svc._con.execute("SELECT seq,tx,tick,kind,ref,data_json FROM world_log WHERE seq>? AND kind IN "
                                      "('create','update','delete','link','unlink') ORDER BY seq", (s["seq"],)).fetchall()
        s["seq"] = self._svc_head()
        events, before = [], None
        txs: dict = {}
        for seq, tx, tick, kind, ref, data in rows:
            txs.setdefault(tx, []).append((seq, tick, kind, ref, json.loads(data)))
        for _tx, grp in txs.items():
            before = self.view_for(sub, (s["objs"], s["links"]))
            for _seq, _tick, kind, ref, data in grp:
                if kind in ("create", "update"):
                    s["objs"][ref] = data["props"]
                elif kind == "delete":
                    s["objs"].pop(ref, None)
                elif kind == "link":
                    s["links"].add((data["link_type"], data["src"], data["dst"]))
                else:
                    s["links"].discard((data["link_type"], data["src"], data["dst"]))
            after = self.view_for(sub, (s["objs"], s["links"]))
            events += self._tx_events(s, grp, before, after)
        return CallResult("OK", {"events": sorted(events, key=lambda e: e["seq"])})

    def _tx_events(self, s: dict, grp: list, before: LowView, after: LowView) -> list:
        out, last = [], {}
        for seq, tick, kind, ref, data in grp:
            key = (data["link_type"], data["src"], data["dst"]) if kind in ("link", "unlink") else ref
            last[key] = (seq, tick, kind, data)
        for key, (seq, tick, kind, data) in last.items():
            if isinstance(key, tuple):
                lt, a, b = key
                if not ({split(a)[0], split(b)[0]} & s["types"]):
                    continue
                if "subscription_unfiltered" in self.mutants:   # MUTANT: every committed change is delivered
                    out.append({"seq": seq, "tick": tick, "kind": kind, "link": [lt, a, b], "props": {}})
                    continue
                was, now = key in before.links, key in after.links
                if was != now:
                    out.append({"seq": seq, "tick": tick, "kind": "link" if now else "unlink", "link": [lt, a, b], "props": {}})
                continue
            if split(key)[0] not in s["types"]:
                continue
            if "subscription_unfiltered" in self.mutants:
                out.append({"seq": seq, "tick": tick, "kind": kind, "ref": key, "props": dict(data.get("props", {}))})
                continue
            was, now = before.objects.get(key), after.objects.get(key)
            if was is None and now is not None:
                out.append({"seq": seq, "tick": tick, "kind": "create", "ref": key, "props": dict(now)})
            elif was is not None and now is None:
                out.append({"seq": seq, "tick": tick, "kind": "delete", "ref": key, "props": {}})
            elif was is not None and was != now:
                out.append({"seq": seq, "tick": tick, "kind": "update", "ref": key,
                            "props": {f: v for f, v in now.items() if was.get(f, object()) != v}})
        return out
