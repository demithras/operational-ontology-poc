"""Knowledge sovereignty, part 3: provenance views (PROT-H26 s4, P1e-5). prov_decision / prov_object / authority_used_as.

A decision is recorded once (`note_decision`, called when its envelope is anchored) with the facts the views need: scalars,
resource refs, the edge ids of the authority document it ran under, and a compact description of the rows it wrote. A view
returns the TRUE value of a field only when every byte it covers is low for the observer; otherwise the explicit marker
{"redacted": kind} (never "unknown"/null/"system"). `partial` is constant true; chain fields never leave the auditor API.

Mutants at the real sites: provenance_edge_retained (hidden edge ids / actors returned unredacted), redaction_fabrication
(redacted actors replaced by the string "system" without a marker).
"""
from __future__ import annotations

from paladin import capgraph, evid
from paladin.public import refusal_code
from paladin.sovview import split
from r3_shared.disclosure import marker
from r3_shared.variant import CallResult

UNKNOWN = CallResult("INVALID", {"reason": "unknown_decision"})


def _inputs_of(node, out: list) -> None:
    if isinstance(node, dict):
        if set(node) == {"input"}:
            out.append(node["input"])
        for v in node.values():
            _inputs_of(v, out)
    elif isinstance(node, list):
        for v in node:
            _inputs_of(v, out)


class SovProvMixin:
    def scalar_flows(self, op, args) -> list:
        """(type, field) pairs a SCALAR input present in the request flows into through create/update effects."""
        o = self.ops.get(op) if isinstance(op, str) else None
        if o is None or not isinstance(args, dict):
            return []
        scalars = {i["name"] for i in o["inputs"] if i["type"] != "resource" and i["name"] in args}
        out = []
        for e in o["effects"]:
            if e["kind"] in ("create", "update"):
                for f, expr in (e.get("props") or {}).items():
                    names: list = []
                    _inputs_of(expr, names)
                    if scalars & set(names):
                        out.append([e["type"], f])
        return out

    def _has_scalars(self, op, args) -> bool:
        """Is any non-resource (scalar) input present in the request? (G3-E26 INTERP-2)"""
        o = self.ops.get(op) if isinstance(op, str) else None
        if o is None or not isinstance(args, dict):
            return bool(args)
        return any(i["type"] != "resource" and i["name"] in args for i in o["inputs"])

    def note_decision(self, d: dict, res=None) -> None:
        """Remember what the provenance views need about an anchored decision (ledger meta: durable, HistoryStore in H27 runs)."""
        sc = self.prov.decision_scalars(d)
        op, args = d["op"], d["args"]
        refs = [list(r) for r in evid.input_refs(self.ops_spec, op, args)] if isinstance(op, str) and op in self.ops \
            and isinstance(args, dict) else []
        rows = []
        for r in d["rows"]:
            if r["kind"] in ("create", "update", "delete"):
                data = r["data"]
                fs = sorted(set(data.get("props", {})) | set(data.get("patch", {})) if r["kind"] == "update" else set(data.get("props", {})))  # RC8: every property of the touched object
                rows.append({"k": r["kind"], "r": r["ref"], "f": fs})
            elif r["kind"] in ("link", "unlink"):
                rows.append({"k": r["kind"], "l": [r["data"]["link_type"], r["data"]["src"], r["data"]["dst"]]})
            elif r["kind"] == "external":
                rows.append({"k": "external"})
            else:
                rows.append({"k": "mark", "r": r["ref"], "c": r["data"].get("case") if r["ref"] == "governance" else None,
                             "g": r["ref"] == "governance"})
        rec = {"s": sc, "refs": refs, "edges": [e["id"] for e in d["doc"].get("capabilities", ())], "rows": rows,
               "flows": self.scalar_flows(op, args), "sc": self._has_scalars(op, args),
               "vr": ("ok" if res is None or res.status == "OK" else refusal_code(res.body))}   # G3-E27: the PUBLIC reply reason
        self.ledger.put_meta("dec:" + sc["decision_id"], rec)
        idx = self.ledger.get_meta("decidx") or []
        idx.append(sc["decision_id"])
        self.ledger.put_meta("decidx", idx)

    # ---- lowness of a decision and of the bytes its digests cover -------------------------------------------------
    def _own(self, sub: str, s: dict) -> bool:
        return sub in (s["subject"], s["on_behalf_of"])

    def _low_decision(self, sub, rec, view) -> bool:
        refs = [f"{t}:{k}" for t, k in rec["refs"]]
        return self._own(sub, rec["s"]) or (bool(refs) and all(r in view.objects and view.level.get(r) in ("scalars", "actors")
                                                              for r in refs))

    def _args_low(self, sub, rec, view) -> bool:
        if self._own(sub, rec["s"]):
            return True
        refs = [f"{t}:{k}" for t, k in rec["refs"]]
        # G3-E26 INTERP-2: a non-own decision's args are low only if they are made of existence-visible resource refs alone
        # (no scalar inputs present); "the scalar flows into a field the observer sees" never makes them low.
        return all(r in view.objects for r in refs) and not rec.get("sc", bool(rec["flows"]))

    def _eff_low(self, sub, rec, view) -> bool:
        # G3-E22: the own-decision exemption covers args_digest only; effect_digest covers the full rows (all props/patch
        # fields of each touched object), so it is true only if every touched object and field is in the observer's low view.
        edges_hidden = any(not capgraph.edge_visible(self.auth, e, sub) for e in rec["edges"])
        for r in rec["rows"]:
            k = r["k"]
            if k in ("create", "update", "delete"):
                if r["r"] not in view.objects or not set(r["f"]) <= set(view.fields_of.get(r["r"], ())):
                    return False
            elif k in ("link", "unlink"):
                if tuple(r["l"]) not in view.links:
                    return False
            elif k == "external":
                return False   # the row's ref ("adapter:target#seq") is an outside-system effect, never an object in the low view
            elif r["r"] == "commit" and edges_hidden:   # the commit mark carries the authority_version digest
                return False
            elif r["g"]:
                c = self.book.cases.get(r["c"]) if self.book is not None and r["c"] else None
                if c is None or sub not in self.book.seers(c):
                    return False
        return True

    def prov_decision(self, sub: str, did) -> CallResult:
        rec = self.ledger.get_meta("dec:" + did) if isinstance(did, str) else None
        if rec is None:
            return UNKNOWN
        view = self.view_for(sub)
        if not self._low_decision(sub, rec, view):
            return UNKNOWN
        s, retain = rec["s"], "provenance_edge_retained" in self.mutants
        refs = [f"{t}:{k}" for t, k in rec["refs"]]
        actors = self._own(sub, s) or retain or all(view.level.get(r) == "actors" for r in refs)
        out = dict(s)
        out["reason"] = rec.get("vr", s["reason"])   # G3-E27: the public reply reason; gate codes stay auditor-only
        if not actors:
            for f in ("subject", "on_behalf_of"):
                out[f] = "system" if "redaction_fabrication" in self.mutants else marker("actor")   # MUTANT: no marker
        if not self._args_low(sub, rec, view):
            out["args_digest"] = marker("args")
        if not self._eff_low(sub, rec, view):
            out["effect_digest"] = marker("digest")
        if not retain and any(not capgraph.edge_visible(self.auth, e, sub) for e in s["authority_path"]):
            out["authority_path"] = marker("edge")
        return CallResult("OK", {"partial": True, "decision": out})

    def prov_object(self, sub: str, ref) -> CallResult:
        view = self.view_for(sub)
        if not isinstance(ref, str) or ref not in view.objects:
            return CallResult("OK", {"partial": True, "decisions": []})   # G3-E19: absent == hidden == empty
        out = []
        for did in self.ledger.get_meta("decidx") or []:
            rec = self.ledger.get_meta("dec:" + did)
            if rec is not None and [*split(ref)] in rec["refs"] and self._low_decision(sub, rec, view):
                out.append(did)
        return CallResult("OK", {"partial": True, "decisions": out})

    def authority_used_as(self, sub: str, rid) -> CallResult:
        led = self.ledger.get(rid) if isinstance(rid, str) else None
        used = self.ledger.get_meta(f"used:{rid}") if led is not None else None
        if led is None or led["state"] != "COMMITTED" or led["sub"] != sub or not used:
            rec = self.ledger.get_meta("dec:" + rid) if isinstance(rid, str) else None
            if rec is not None and self._own(sub, rec["s"]) and rec["s"]["status"] != "OK":   # G3-E27: own refused request
                s = rec["s"]
                return CallResult("OK", {"partial": True, "on_behalf_of": s["on_behalf_of"], "path": [],
                                         "authority_version": marker("digest"), "world_seq": s["world_seq"], "tick": s["tick"]})
            return UNKNOWN
        retain = "provenance_edge_retained" in self.mutants
        path = [e if (retain or capgraph.edge_visible(self.auth, e, sub)) else marker("edge") for e in used["path"]]
        return CallResult("OK", {"partial": True, "on_behalf_of": used["on_behalf_of"], "path": path,
                                 "authority_version": marker("digest"), "world_seq": used["world_seq"], "tick": used["tick"]})
