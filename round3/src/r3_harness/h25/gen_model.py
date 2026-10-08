"""Governance model instances (ORACLE-AND-HARNESS-G3 A2): per case, mutate one of the 3 frozen family fixtures WITHIN its
family (fresh principals, member draws, k, windows, ranks, key subsets, lapse delays), re-validate with BOTH the oracle's
static rules and r3_shared.validate_governance, and add `emergency:*` grants for the emergency matter's bodies so a
declaration has base authority. Never raises: an impossible draw is re-drawn and counted; after 25 tries the pristine
fixture is used (also counted)."""
from __future__ import annotations

import copy
import functools
import json
import random
from pathlib import Path

from r3_oracle.const_static import static_errors
from r3_shared.authspec import validate_strict
from r3_shared.governance import MODELS, load_governance, validate_governance
from r3_shared.opsspec import load_ops_spec

ROUND3 = Path(__file__).resolve().parents[3]
DOMAINS = ("manufacturing", "project")


@functools.lru_cache(None)
def specs(domain: str):
    auth = json.loads((ROUND3 / "spec" / "authority" / f"{domain}.v3.json").read_text())
    return load_ops_spec(domain), auth


@functools.lru_cache(None)
def fixture(model: str, domain: str) -> dict:
    return load_governance(model, domain)


def _seed_keys(ops: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for o in ops["seed"]["objects"]:
        out.setdefault(o["type"], []).append(o["key"])
    return out


def _fresh(auth: dict, rng: random.Random, n: int) -> list[str]:
    tmpl = [p for p in auth["principals"] if p["delegated_by"] is None and p["kind"] == "human"] or auth["principals"]
    ids = []
    for k in range(n):
        t = copy.deepcopy(rng.choice(tmpl))
        t["id"] = f"u{rng.randrange(10 ** 5):05d}-{k}"
        auth["principals"].append(t)
        ids.append(t["id"])
    return ids


def _mutate(doc: dict, pool: list[str], ops: dict, rng: random.Random) -> None:
    for b in doc["bodies"]:
        if b["rule"]["kind"] == "single":
            b["members"] = [rng.choice(pool)]
        else:
            n = rng.randint(3, min(7, len(pool)))
            b["members"] = rng.sample(pool, n)
            b["rule"]["k"] = rng.randint((n + 1) // 2, n) if rng.random() < 0.7 else rng.randint(1, n)
            b["rule"]["recuse"] = rng.choice([[], ["requester"]])
        b["rank"] = rng.randint(0, 4)
    keys = _seed_keys(ops)
    for m in doc["matters"]:
        for e in m["scope"]["resources"]:
            if e["keys"] is not None and keys.get(e["type"]):
                e["keys"] = rng.sample(keys[e["type"]], rng.randint(1, min(3, len(keys[e["type"]]))))
        if m["review"]:
            m["review"]["window"] = rng.randint(1, 6)
        if isinstance(m["on_absent"], dict):
            m["on_absent"] = {"lapse": rng.choice(["allow", "deny"]), "after": rng.randint(2, 9)}
    if doc["emergency"]:
        doc["emergency"]["max_duration"] = rng.randint(4, 14)


def _grant_declarers(auth: dict, doc: dict) -> None:
    em = doc["emergency"]
    if not em:
        return
    mat = next(m for m in doc["matters"] if m["id"] == em["matter"])
    who = sorted({p for b in doc["bodies"] if b["id"] in mat["competent"] for p in b["members"]})
    for p in who:
        auth["grants"].append({"id": f"emerg-declare-{p}", "effect": "allow", "operation": "emergency:*", "delegable": False,
                               "origin": "neutral-extension", "principal": {"id": p}, "resource": {"any": True}})


def make_instance(model: str, domain: str, seed) -> dict:
    """-> {model, domain, doc, auth, ops, redraws}. Deterministic in (model, domain, seed)."""
    rng = random.Random(f"h25-model-{model}-{domain}-{seed}")
    ops, auth0 = specs(domain)
    redraws = 0
    for attempt in range(25):
        auth = copy.deepcopy(auth0)
        fresh = _fresh(auth, rng, rng.randint(6, 14))
        pool = fresh + [p["id"] for p in auth0["principals"] if p["delegated_by"] is None]
        doc = copy.deepcopy(fixture(model, domain))
        _mutate(doc, pool, ops, rng)
        _grant_declarers(auth, doc)
        try:
            validate_strict(auth, ops)
            validate_governance(doc, auth, ops)
            if static_errors(doc, auth, ops):
                raise ValueError("oracle static rules disagree")
            return {"model": model, "domain": domain, "doc": doc, "auth": auth, "ops": ops, "redraws": redraws}
        except ValueError:
            redraws += 1
    auth = copy.deepcopy(auth0)
    doc = copy.deepcopy(fixture(model, domain))
    _grant_declarers(auth, doc)
    return {"model": model, "domain": domain, "doc": doc, "auth": auth, "ops": ops, "redraws": redraws + 25}


# -- invalid documents (5% of cases include a set_governance with one of these) -------------------------------------
def _cycle(d, rng, auth):
    ids = [b["id"] for b in d["bodies"]]
    a, b = (rng.sample(ids, 2) if len(ids) > 1 else (ids[0], ids[0]))
    d["superior"] = d["superior"] + [[a, b], [b, a]]


def _k_gt_n(d, rng, auth):
    q = [b for b in d["bodies"] if b["rule"]["kind"] == "quorum"]
    if q:
        b = rng.choice(q)
        b["rule"]["k"] = len(b["members"]) + 1
    else:
        d["bodies"].append(copy.deepcopy(d["bodies"][0]))


def _review_competent(d, rng, auth):
    m = d["matters"][0]
    m["review"] = {"by": m["competent"][0], "window": 2}


def _case_state(d, rng, auth):
    d["cases"] = []


def _static_delegate(d, rng, auth):
    dele = [p["id"] for p in auth["principals"] if p["delegated_by"]]
    d["bodies"][0]["members"][0] = dele[0] if dele else "ghost-member"


def _dup_prec(d, rng, auth):
    d["precedence"] = ["rank", "rank"]


INVALID = (_cycle, _k_gt_n, _review_competent, _case_state, _static_delegate, _dup_prec)


def invalid_doc(inst: dict, rng: random.Random) -> tuple[dict, str]:
    """-> (an INVALID document derived from the instance's, mutation name). Guaranteed rejected by both validators."""
    for _ in range(10):
        f = rng.choice(INVALID)
        d = copy.deepcopy(inst["doc"])
        f(d, rng, inst["auth"])
        if static_errors(d, inst["auth"], inst["ops"]):
            return d, f.__name__
    d = copy.deepcopy(inst["doc"])
    d["cases"] = []
    return d, "_case_state"


def valid_variant(inst: dict, rng: random.Random) -> dict:
    """A different VALID document of the same instance family (for mid-case set_governance)."""
    for _ in range(10):
        d = copy.deepcopy(inst["doc"])
        for b in d["bodies"]:
            if b["rule"]["kind"] == "quorum" and rng.random() < 0.6:
                b["rule"]["k"] = rng.randint(1, len(b["members"]))
        for m in d["matters"]:
            if m["review"]:
                m["review"]["window"] = rng.randint(1, 6)
        d["precedence"] = rng.sample(["specialis", "superior", "rank"], rng.randint(0, 3))
        if not static_errors(d, inst["auth"], inst["ops"]):
            return d
    return copy.deepcopy(inst["doc"])


_ = MODELS
