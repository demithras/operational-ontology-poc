"""Generated governance documents for P1e tests (seeded; never raises). Mutations are listed as (name, valid?) so a
test can check accept/reject against an independent reference. `ref_static_ok` is a TEST-LOCAL independent
re-implementation of the PROT-H25 s1 static rules (the oracle's r3_oracle/constitution.py will be compared the same way)."""
from __future__ import annotations

import copy
import functools
import random

from r3_shared.authspec import load_auth_spec
from r3_shared.governance import MODELS, load_governance
from r3_shared.opsspec import load_ops_spec

DOMAINS = ("manufacturing", "project")
_auth = functools.lru_cache(None)(load_auth_spec)
_ops = functools.lru_cache(None)(load_ops_spec)
_gov = functools.lru_cache(None)(load_governance)


def _cycle(d, rng):
    ids = [b["id"] for b in d["bodies"]]
    a, b = rng.sample(ids, 2) if len(ids) > 1 else (ids[0], ids[0])
    d["superior"] += [[a, b], [b, a]]


def _k_big(d, rng):
    q = [b for b in d["bodies"] if b["rule"]["kind"] == "quorum"]
    if q:
        b = rng.choice(q)
        b["rule"]["k"] = len(b["members"]) + 1


def _k_zero(d, rng):
    q = [b for b in d["bodies"] if b["rule"]["kind"] == "quorum"]
    if q:
        rng.choice(q)["rule"]["k"] = 0


def _review_competent(d, rng):
    m = rng.choice([m for m in d["matters"] if m["review"]] or d["matters"])
    m["review"] = {"by": m["competent"][0], "window": 2}


def _unknown_member(d, rng):
    b = rng.choice(d["bodies"])
    b["members"] = b["members"] + ["ghost-principal"] if b["rule"]["kind"] == "quorum" else ["ghost-principal"]


def _dup_body(d, rng):
    d["bodies"].append(copy.deepcopy(rng.choice(d["bodies"])))


def _case_key(d, rng):
    d["cases"] = []


def _dup_prec(d, rng):
    d["precedence"] = ["rank", "rank"]


def _bad_emerg(d, rng):
    if d["emergency"]:
        mid = d["emergency"]["matter"]
        for m in d["matters"]:
            if m["id"] == mid:
                m["scope"]["operations"].append("reschedule_work_order")


def _window0(d, rng):
    for m in d["matters"]:
        if m["review"]:
            m["review"]["window"] = 0


def _single_two(d, rng):
    s = [b for b in d["bodies"] if b["rule"]["kind"] == "single"]
    if s:
        rng.choice(s)["members"].append("x-extra")


def _emerg_missing(d, rng):
    if d["emergency"]:
        d["emergency"]["matter"] = "no-such-matter"


def _ceiling_unknown(d, rng):
    if d["emergency"]:
        d["emergency"]["ceiling"]["operations"].append("no_such_operation")


def _lapse0(d, rng):
    for m in d["matters"]:
        m["on_absent"] = {"lapse": "deny", "after": 0}
        break


INVALID = [_cycle, _k_big, _k_zero, _review_competent, _unknown_member, _dup_body, _case_key, _dup_prec, _bad_emerg,
           _window0, _single_two, _emerg_missing, _ceiling_unknown, _lapse0]


def _k_ok(d, rng):
    for b in d["bodies"]:
        if b["rule"]["kind"] == "quorum":
            b["rule"]["k"] = rng.randint(1, len(b["members"]))


def _window_ok(d, rng):
    for m in d["matters"]:
        if m["review"]:
            m["review"]["window"] = rng.randint(1, 9)


def _prec_ok(d, rng):
    d["precedence"] = rng.sample(["specialis", "superior", "rank"], rng.randint(0, 3))


def _ranks(d, rng):
    for b in d["bodies"]:
        b["rank"] = rng.randint(0, 5)


def _no_emerg(d, rng):
    d["emergency"] = None


def _lapse_ok(d, rng):
    for m in d["matters"]:
        m["on_absent"] = rng.choice(["await", {"lapse": "allow", "after": rng.randint(1, 9)}])


VALID = [_k_ok, _window_ok, _prec_ok, _ranks, _no_emerg, _lapse_ok]


def gen_doc(seed: int):
    """-> (doc, auth_spec, ops_spec, applied mutation names). Never raises."""
    rng = random.Random(seed)
    dom, model = rng.choice(DOMAINS), rng.choice(MODELS)
    d = copy.deepcopy(_gov(model, dom))
    names = []
    for f in rng.sample(VALID, rng.randint(0, 3)) + rng.sample(INVALID, rng.choice([0, 0, 1, 1, 2])):
        f(d, rng)
        names.append(f.__name__)
    if rng.random() < 0.1:  # a static delegate as member (manufacturing only has them)
        auth = _auth(dom)
        dele = [p["id"] for p in auth["principals"] if p["delegated_by"]]
        if dele:
            d["bodies"][0]["members"][0] = dele[0]
            names.append("static_delegate")
    return d, _auth(dom), _ops(dom), names


def ref_static_ok(doc, auth, ops) -> bool:
    """Independent re-statement of PROT-H25 s1 (test-local)."""
    try:
        if set(doc) != {"spec", "model", "domain", "bodies", "superior", "matters", "precedence", "emergency"}:
            return False
        if doc["spec"] != "r3-governance-1" or doc["precedence"] != list(dict.fromkeys(doc["precedence"])):
            return False
        bodies = {}
        for b in doc["bodies"]:
            if b["id"] in bodies or not b["members"]:
                return False
            bodies[b["id"]] = b
        if len({m["id"] for m in doc["matters"]}) != len(doc["matters"]):
            return False
        pr = {p["id"]: p for p in auth["principals"]}
        for b in bodies.values():
            if any(m not in pr or pr[m]["delegated_by"] is not None for m in b["members"]):
                return False
            r = b["rule"]
            if r["kind"] == "single" and len(b["members"]) != 1:
                return False
            if r["kind"] == "quorum" and not (1 <= r["k"] <= len(b["members"])):
                return False
        up = {}
        for lo, hi in doc["superior"]:
            if lo not in bodies or hi not in bodies:
                return False
            up.setdefault(lo, set()).add(hi)
        for start in list(up):  # reachability: a body reaching itself = cycle
            seen, stack = set(), list(up[start])
            while stack:
                n = stack.pop()
                if n == start:
                    return False
                if n not in seen:
                    seen.add(n)
                    stack += list(up.get(n, ()))
        for m in doc["matters"]:
            if not m["competent"] or any(c not in bodies for c in m["competent"]):
                return False
            if m["review"] and (m["review"]["by"] not in bodies or m["review"]["by"] in m["competent"] or m["review"]["window"] < 1):
                return False
            if isinstance(m["on_absent"], dict) and m["on_absent"]["after"] < 1:
                return False
        e = doc["emergency"]
        if e:
            mat = [m for m in doc["matters"] if m["id"] == e["matter"]]
            if not mat or not mat[0]["scope"]["operations"] or set(mat[0]["scope"]["operations"]) != {"emergency:declare"}:
                return False
            names = {o["name"] for o in ops["operations"]} | {o["approval"]["approver_operation"] for o in ops["operations"] if o.get("approval")}
            if e["grantees_from"] not in bodies or not set(e["ceiling"]["operations"]) <= names:
                return False
        return True
    except (KeyError, TypeError):
        return False
