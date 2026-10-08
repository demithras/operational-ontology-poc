"""Oracle: protected non-object layers - decisions, edges, cases - and the redacted provenance views (PROT-H26 s1.3,
s2.3, s4). A DecisionRec is a harness-side dict:
  {"id", "rid", "subject", "on_behalf_of", "approver", "resources": [ref...], "scalars": {12 PROT-H27 s1 keys, TRUE
   values}, "args_refs": [ref...], "args_scalar_free": bool, "effects": [diff rows], "edge_path": [edge id...]}
"""
from __future__ import annotations

from r3_shared.disclosure import DECISION_KEYS, marker

from .disclosure import ORDER


def own_decision(d: dict, observer: str) -> bool:
    return observer in (d.get("subject"), d.get("on_behalf_of"), d.get("approver"))


def _edge_map(edges) -> dict:
    return {e["id"]: e for e in edges}


def edge_path(edges: dict, eid: str) -> list[dict]:
    """Root-first chain of edges ending at eid."""
    out, seen = [], set()
    while eid is not None and eid in edges and eid not in seen:
        seen.add(eid)
        out.append(edges[eid])
        eid = edges[eid].get("parent")
    return out[::-1]


def edge_visible(edges: dict, eid: str, observer: str) -> bool:
    """s1.3: issuer or child of every edge on path(e), and of every edge below e (descendants)."""
    if eid not in edges:
        return False
    people = set()
    for e in edge_path(edges, eid):
        people |= {e["issuer"], e["child"]}
    below = {eid}
    grew = True
    while grew:
        grew = False
        for e in edges.values():
            if e.get("parent") in below and e["id"] not in below:
                below.add(e["id"])
                grew = True
    for b in below:
        people |= {edges[b]["issuer"], edges[b]["child"]}
    return observer in people


def low_edges(edges, observer: str) -> dict:
    m = _edge_map(edges)
    return {eid: m[eid] for eid in sorted(m) if edge_visible(m, eid, observer)}


def case_visible(c: dict, observer: str) -> bool:
    return observer == c["requester"] or observer in c.get("members", ())


def low_cases(cases: dict, observer: str) -> dict:
    return {cid: {"requester": c["requester"], "state": c.get("state")} for cid, c in sorted(cases.items())
            if case_visible(c, observer)}


def _res_ok(lv, d: dict, need: str) -> bool:
    rs = d["resources"]
    return bool(rs) and all(r in lv.objects and ORDER[lv.prov.get(r, "none")] >= ORDER[need] for r in rs)


def decision_low(lv, d: dict) -> bool:
    """s4.1: OWN, or every resource input existence-visible and a covering rule's provenance in {scalars, actors}."""
    return own_decision(d, lv.observer) or _res_ok(lv, d, "scalars")


def _rows_low(lv, rows: list) -> bool:
    """Every field of every world_log row the effect digest covers is in the low view (rows without `data` are skipped)."""
    for row in rows:
        data = row.get("data") or {}
        if row.get("kind") in ("link", "unlink", "mark") or not isinstance(data, dict):
            continue
        r = row.get("ref")
        if r not in lv.objects:
            return False
        names = set(data.get("props") or ()) | set(data.get("patch") or ())
        if not names <= set(lv.objects[r]):
            return False
    return True


def _digest_low(lv, d: dict, kind: str) -> bool:
    """s4.2: a digest is true only if every byte it covers is low. INTERP-2: args bytes are low iff the decision is own,
    or the args are made ONLY of existence-visible resource refs (`args_scalar_free`); effect bytes are low iff every
    object/field/link the effect rows touch is in the low view."""
    if kind == "args":
        if own_decision(d, lv.observer):
            return True
        return bool(d.get("args_scalar_free")) and all(r in lv.objects for r in d.get("args_refs", []))
    # G3-E21 / PROT-H26 s4.2: own decisions are NOT exempt for the effect digest - it covers the transaction's full world_log
    # rows (E-4 form), whose `data.props` carry every property of the touched object, hidden ones included.
    if not _rows_low(lv, d.get("effect_rows", [])):
        return False
    for row in d.get("effects", []):
        if row["kind"] in ("link", "unlink"):
            lt, a, b = row["ref"].split("|", 2)
            if (lt, a, b) not in lv.links:
                return False
            continue
        r = row["ref"]
        if r not in lv.objects:
            return False
        names = set(row["changes"]) if row["kind"] == "update" else set(row.get("props", {}))
        if not names <= set(lv.objects[r]):
            return False
    return True


def expected_decision(lv, d: dict) -> dict | None:
    """Expected redacted decision view for a decision the observer may see; None = unknown (hidden == absent)."""
    if not decision_low(lv, d):
        return None
    own = own_decision(d, lv.observer)
    actors = own or (bool(d["resources"]) and _res_ok(lv, d, "actors"))
    s = dict(d["scalars"])
    em = _edge_map(lv.facts.edges)
    out = {k: s[k] for k in DECISION_KEYS}
    if not actors:
        out["subject"], out["on_behalf_of"] = marker("actor"), marker("actor")
    if not _digest_low(lv, d, "args"):
        out["args_digest"] = marker("digest")
    if not _digest_low(lv, d, "effect"):
        out["effect_digest"] = marker("digest")
    out["authority_path"] = [e if edge_visible(em, e, lv.observer) else marker("edge") for e in d.get("edge_path", [])]
    return out


def find_decision(lv, did: str) -> dict | None:
    return next((d for d in lv.facts.decisions if d["id"] == did), None)


def expected_prov_decision(lv, did: str) -> tuple[str, dict]:
    d = find_decision(lv, did)
    v = None if d is None else expected_decision(lv, d)
    if v is None:
        return "INVALID", {"reason": "unknown_decision"}
    return "OK", {"partial": True, "decision": v}


def expected_prov_object(lv, ref: str) -> tuple[str, dict]:
    ids = [d["id"] for d in lv.facts.decisions if ref in d["resources"] and ref in lv.objects and decision_low(lv, d)]
    return "OK", {"partial": True, "decisions": ids}


def expected_authority_used_as(lv, rid: str) -> tuple[str, dict]:
    d = next((x for x in lv.facts.decisions if x.get("rid") == rid and own_decision(x, lv.observer)), None)
    if d is None:
        return "INVALID", {"reason": "unknown_decision"}
    em = _edge_map(lv.facts.edges)
    path = [e if edge_visible(em, e, lv.observer) else marker("edge") for e in d.get("edge_path", [])]
    s = d["scalars"]
    return "OK", {"partial": True, "on_behalf_of": s["on_behalf_of"], "path": path,
                  "authority_version": marker("digest"), "world_seq": s["world_seq"], "tick": s["tick"]}


def low_decisions(lv) -> dict:
    out = {}
    for d in lv.facts.decisions:
        v = expected_decision(lv, d)
        if v is not None:
            out[d["id"]] = v
    return out
