"""PROT-H25 s2 procedural evaluation as pure functions over (governance doc, ops spec, case dict, commit point).
Oracle choices where the frozen text leaves room are marked ORACLE-CHOICE (reported to the orchestrator):
 - a body kept by `specialis` iff SOME covering matter of it is not a strict superset of another candidate body's matter;
 - the deciding matter is the first matter in document order that covers the request (concurrence) or names the winner;
 - a lapse is fixed at tick propose_tick + after (not at the first later transaction): derived from marks and ticks only;
 - a case that is no longer governed (or unresolved) under the document in force is AWAITING (explicit refusal, R25-5).
Merit is never an input: judgments are (judge, stage, value, rid, seq, tick)."""
from __future__ import annotations

from . import ops_model
from . import scope_v2 as sc

AWAIT, ALLOW, DENY = "AWAITING", "ALLOW", "DENY"
YES = {"decision": "concur", "review": "uphold"}
NO = {"decision": "dissent", "review": "overturn"}


def resources_for(ops: dict, operation: str, args) -> list[tuple[str, str]]:
    op = ops_model.op_of(ops, operation)
    return ops_model.resources_of(op, args) if op and isinstance(args, dict) else []


def covering(doc: dict, operation: str, resources) -> list[dict]:
    return [m for m in doc["matters"] if sc.covers(m["scope"], operation, resources)]


def body_of(doc: dict, bid: str) -> dict:
    return next(b for b in doc["bodies"] if b["id"] == bid)


def _above(doc: dict, lo: str) -> set[str]:
    up: dict[str, set] = {}
    for a, b in doc["superior"]:
        up.setdefault(a, set()).add(b)
    seen, todo = set(), [lo]
    while todo:
        for h in up.get(todo.pop(), ()):
            if h not in seen:
                seen.add(h)
                todo.append(h)
    return seen


def _strict_sub(a: dict, b: dict) -> bool:
    return sc.subset(a, b) and not (sc.subset(b, a))


def competent(doc: dict, operation: str, resources) -> tuple[str, list[str], list[dict], dict | None]:
    """-> (status, deciding body ids, covering matters, deciding matter). status: OK | not_governed | matter_conflict |
    precedence_unresolved."""
    ms = covering(doc, operation, resources)
    if not ms:
        return "not_governed", [], [], None
    if len({m["concurrence"] for m in ms}) > 1:
        return "matter_conflict", [], ms, None
    cand = sorted({c for m in ms for c in m["competent"]})
    if ms[0]["concurrence"]:
        return "OK", cand, ms, ms[0]
    scopes = {c: [m["scope"] for m in ms if c in m["competent"]] for c in cand}
    for crit in doc["precedence"]:
        if crit == "specialis":
            cand = [c for c in cand if any(
                not any(_strict_sub(o, s) for d in cand if d != c for o in scopes[d]) for s in scopes[c])]
        elif crit == "superior":
            cand = [c for c in cand if not any(d in _above(doc, c) for d in cand)]
        else:
            top = max(body_of(doc, c)["rank"] for c in cand)
            cand = [c for c in cand if body_of(doc, c)["rank"] == top]
    if len(cand) != 1:
        return "precedence_unresolved", [], ms, None
    return "OK", cand, ms, next(m for m in ms if cand[0] in m["competent"])


def eligible(doc: dict, bid: str, requester: str) -> list[str]:
    b = body_of(doc, bid)
    recuse = b["rule"].get("recuse", [])
    out: list[str] = []
    for m in b["members"]:
        if "requester" in recuse and m == requester:
            continue
        if m not in out:
            out.append(m)
    return out


def _body_result(doc, bid, requester, js, stage) -> str:
    el = eligible(doc, bid, requester)
    cnt = [j for j in js if j["judge"] in el]
    yes = sum(j["value"] == YES[stage] for j in cnt)
    no = sum(j["value"] == NO[stage] for j in cnt)
    r = body_of(doc, bid)["rule"]
    if r["kind"] == "single":
        return ALLOW if yes else DENY if no else AWAIT
    k, n = r["k"], len(el)
    if n < k:
        return AWAIT
    if stage == "review":  # PROT-H25 2.4: overturn >= k -> OVERTURNED (no dissent > n-k shortcut)
        return ALLOW if yes >= k else DENY if no >= k else AWAIT
    return ALLOW if yes >= k else DENY if no > n - k else AWAIT


def _combine(doc, bodies, conc, requester, js, stage) -> str:
    rs = [_body_result(doc, b, requester, js, stage) for b in bodies]
    if not conc:
        return rs[0]
    return ALLOW if all(r == ALLOW for r in rs) else DENY if DENY in rs else AWAIT


def _first_per_judge(js, bodies, doc, requester):
    seen, out = set(), []
    allowed = {m for b in bodies for m in eligible(doc, b, requester)}
    for j in sorted(js, key=lambda x: x["seq"]):
        if j["judge"] in allowed and j["judge"] not in seen:
            seen.add(j["judge"])
            out.append(j)
    return out


def _stage(doc, case, stage, bodies, conc, seq, deadline):
    js = [j for j in case["judgments"] if j["stage"] == stage and j["seq"] < seq]
    if deadline is not None:
        js = [j for j in js if j["tick"] < deadline]
    cnt = _first_per_judge(js, bodies, doc, case["requester"])
    for k in range(1, len(cnt) + 1):
        out = _combine(doc, bodies, conc, case["requester"], cnt[:k], stage)
        if out != AWAIT:
            return {"outcome": out, "basis": "judged", "seq": cnt[k - 1]["seq"], "tick": cnt[k - 1]["tick"],
                    "counted": [j["rid"] for j in cnt[:k]]}
    return {"outcome": AWAIT, "basis": None, "seq": None, "tick": None, "counted": []}


def decision(doc: dict, ops: dict, case: dict, seq: int, tick: int) -> dict:
    """Decision stage at commit point (seq, tick) (judgments committed before seq). Adds `st` (competent status),
    `bodies`, `matter` to the stage dict."""
    st, bodies, ms, matter = competent(doc, case["operation"], resources_for(ops, case["operation"], case["args"]))
    if st != "OK":
        return {"outcome": AWAIT, "basis": None, "seq": None, "tick": None, "counted": [], "st": st, "bodies": [],
                "matter": None, "ms": ms}
    oa = matter["on_absent"]
    deadline = case["ptick"] + oa["after"] if oa != "await" else None
    out = _stage(doc, case, "decision", bodies, matter["concurrence"], seq, deadline)
    if out["outcome"] == AWAIT and deadline is not None and tick >= deadline:
        out = {"outcome": ALLOW if oa["lapse"] == "allow" else DENY, "basis": "lapse", "seq": None, "tick": deadline,
               "counted": []}
    return {**out, "st": "OK", "bodies": bodies, "matter": matter, "ms": ms}


def appealed(case: dict, seq: int) -> bool:
    return case["appeal"] is not None and case["appeal"]["seq"] < seq


def review(doc: dict, ops: dict, case: dict, d: dict, seq: int) -> dict:
    rv = d["matter"]["review"] if d["matter"] else None
    if rv is None or not appealed(case, seq):
        return {"outcome": AWAIT, "basis": None, "seq": None, "tick": None, "counted": []}
    out = _stage(doc, case, "review", [rv["by"]], False, seq, None)
    return {**out, "outcome": {ALLOW: "UPHELD", DENY: "OVERTURNED"}.get(out["outcome"], AWAIT)}


def final(doc: dict, ops: dict, case: dict, seq: int, tick: int) -> dict:
    """-> {state: FINAL|AWAITING|NOT_FINAL, outcome: ALLOW|DENY|None, rule, basis, dec, rev}."""
    d = decision(doc, ops, case, seq, tick)
    res = {"state": AWAIT, "outcome": None, "rule": None, "basis": [], "dec": d, "rev": None}
    if d["outcome"] == AWAIT:
        return res
    rv = d["matter"]["review"]
    own = "lapse" if d["basis"] == "lapse" else "decision"
    if rv is None or (not appealed(case, seq) and tick >= d["tick"] + rv["window"]):
        return {**res, "state": "FINAL", "outcome": d["outcome"], "rule": own, "basis": d["counted"]}
    if not appealed(case, seq):
        return {**res, "state": "NOT_FINAL"}
    r = review(doc, ops, case, d, seq)
    res["rev"] = r
    if r["outcome"] == AWAIT:
        return res
    flip = {ALLOW: DENY, DENY: ALLOW}
    return {**res, "state": "FINAL", "outcome": d["outcome"] if r["outcome"] == "UPHELD" else flip[d["outcome"]],
            "rule": "review", "basis": d["counted"] + r["counted"]}


def sees(doc: dict, ops: dict, case: dict, who: str) -> bool:
    """Case visibility (PROT-H25 3.1): requester, members of competent and reviewing bodies of the covering matters."""
    if who == case["requester"]:
        return True
    ms = covering(doc, case["operation"], resources_for(ops, case["operation"], case["args"]))
    bodies = {c for m in ms for c in m["competent"]} | {m["review"]["by"] for m in ms if m["review"]}
    return any(who in body_of(doc, b)["members"] for b in bodies)
