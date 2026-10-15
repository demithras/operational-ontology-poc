"""Static rules of the governance document (PROT-H25 s1 + errata G3-E5), re-implemented for the oracle: no jsonschema,
no import of r3_shared.governance. `static_errors(doc, auth_spec, ops_spec)` -> list of violated rules ([] = valid).
A parity test compares accept/reject with r3_shared.governance.validate_governance on generated documents (G3-E10)."""
from __future__ import annotations

EMERGENCY_OP = "emergency:declare"
_TOP = {"spec", "model", "domain", "bodies", "superior", "matters", "precedence", "emergency"}
_isint = lambda x: isinstance(x, int) and not isinstance(x, bool)  # noqa: E731
_isstr = lambda x: isinstance(x, str)  # noqa: E731


def _scope_shape(s) -> bool:
    if not isinstance(s, dict) or set(s) != {"operations", "resources"}:
        return False
    if not isinstance(s["operations"], list) or not all(map(_isstr, s["operations"])):
        return False
    if not isinstance(s["resources"], list):
        return False
    for r in s["resources"]:
        if not isinstance(r, dict) or set(r) != {"type", "keys"} or not _isstr(r["type"]):
            return False
        if r["keys"] is not None and not (isinstance(r["keys"], list) and all(map(_isstr, r["keys"]))):
            return False
    return True


def _rule_shape(r) -> bool:
    if not isinstance(r, dict):
        return False
    if r.get("kind") == "single":
        return set(r) == {"kind"}
    if r.get("kind") == "quorum":
        return (set(r) == {"kind", "k", "recuse"} and _isint(r["k"]) and r["k"] >= 1 and isinstance(r["recuse"], list)
                and len(r["recuse"]) <= 1 and all(x == "requester" for x in r["recuse"]))
    return False


def _body_shape(b) -> bool:
    return (isinstance(b, dict) and set(b) == {"id", "members", "rule", "rank"} and _isstr(b["id"]) and b["id"] != ""
            and isinstance(b["members"], list) and len(b["members"]) >= 1 and all(map(_isstr, b["members"]))
            and _rule_shape(b["rule"]) and _isint(b["rank"]))


def _matter_shape(m) -> bool:
    if not isinstance(m, dict) or set(m) != {"id", "scope", "competent", "concurrence", "review", "on_absent"}:
        return False
    if not (_isstr(m["id"]) and m["id"] != "" and _scope_shape(m["scope"]) and isinstance(m["concurrence"], bool)):
        return False
    if not (isinstance(m["competent"], list) and len(m["competent"]) >= 1 and all(map(_isstr, m["competent"]))):
        return False
    rv = m["review"]
    if rv is not None and not (isinstance(rv, dict) and set(rv) == {"by", "window"} and _isstr(rv["by"])
                               and _isint(rv["window"]) and rv["window"] >= 1):
        return False
    oa = m["on_absent"]
    if oa == "await":
        return True
    return (isinstance(oa, dict) and set(oa) == {"lapse", "after"} and oa["lapse"] in ("allow", "deny")
            and _isint(oa["after"]) and oa["after"] >= 1)


def shape_errors(doc) -> list[str]:
    if not isinstance(doc, dict) or set(doc) != _TOP:
        return ["top-level keys"]
    out = []
    if doc["spec"] != "r3-governance-1":
        out.append("spec")
    if not (_isstr(doc["model"]) and doc["model"]) or doc["domain"] not in ("manufacturing", "project"):
        out.append("model/domain")
    if not (isinstance(doc["bodies"], list) and doc["bodies"] and all(_body_shape(b) for b in doc["bodies"])):
        out.append("bodies")
    if not (isinstance(doc["superior"], list) and all(isinstance(e, list) and len(e) == 2 and all(map(_isstr, e))
                                                      for e in doc["superior"])):
        out.append("superior")
    if not (isinstance(doc["matters"], list) and doc["matters"] and all(_matter_shape(m) for m in doc["matters"])):
        out.append("matters")
    if not (isinstance(doc["precedence"], list) and all(x in ("specialis", "superior", "rank") for x in doc["precedence"])):
        out.append("precedence")
    em = doc["emergency"]
    if em is not None and not (isinstance(em, dict) and set(em) == {"matter", "max_duration", "ceiling", "grantees_from"}
                               and _isstr(em["matter"]) and _isint(em["max_duration"]) and em["max_duration"] >= 1
                               and _scope_shape(em["ceiling"]) and _isstr(em["grantees_from"])):
        out.append("emergency")
    return out


def _cyclic(edges) -> bool:
    nxt: dict = {}
    for lo, hi in edges:
        nxt.setdefault(lo, set()).add(hi)
    color: dict = {}

    def dfs(n) -> bool:
        color[n] = 1
        for h in nxt.get(n, ()):
            if color.get(h) == 1 or (h not in color and dfs(h)):
                return True
        color[n] = 2
        return False
    return any(n not in color and dfs(n) for n in list(nxt))


def static_errors(doc, auth_spec: dict, ops_spec: dict) -> list[str]:
    errs = shape_errors(doc)
    if errs:
        return errs
    out: list[str] = []
    if doc["domain"] != auth_spec.get("domain"):
        out.append("domain")
    princ = {p["id"]: p for p in auth_spec["principals"]}
    ids = [b["id"] for b in doc["bodies"]]
    if len(set(ids)) != len(ids):
        out.append("duplicate body ids")
    if len({m["id"] for m in doc["matters"]}) != len(doc["matters"]):
        out.append("duplicate matter ids")
    for b in doc["bodies"]:
        for m in b["members"]:
            if m not in princ or princ[m]["delegated_by"] is not None:
                out.append(f"member {m}")
        n, r = len(b["members"]), b["rule"]
        if r["kind"] == "single" and n != 1:
            out.append(f"single body {b['id']} size")
        if r["kind"] == "quorum" and not 1 <= r["k"] <= n:
            out.append(f"k of {b['id']}")
    known = set(ids)
    if any(lo not in known or hi not in known for lo, hi in doc["superior"]):
        out.append("superior names unknown body")
    elif _cyclic([tuple(e) for e in doc["superior"]]):
        out.append("superior cycle")
    for m in doc["matters"]:
        if any(c not in known for c in m["competent"]):
            out.append(f"matter {m['id']} competent")
        rv = m["review"]
        if rv is not None and (rv["by"] not in known or rv["by"] in m["competent"]):
            out.append(f"matter {m['id']} review")
    if len(set(doc["precedence"])) != len(doc["precedence"]):
        out.append("precedence duplicates")
    em = doc["emergency"]
    if em is not None:
        mat = next((m for m in doc["matters"] if m["id"] == em["matter"]), None)
        if mat is None or not mat["scope"]["operations"] or set(mat["scope"]["operations"]) != {EMERGENCY_OP}:
            out.append("emergency matter")
        if em["grantees_from"] not in known:
            out.append("grantees_from")
        names = {o["name"] for o in ops_spec["operations"]} | {
            o["approval"]["approver_operation"] for o in ops_spec["operations"] if o.get("approval")}
        if any(o not in names for o in em["ceiling"]["operations"]):
            out.append("ceiling operation")
    return out
