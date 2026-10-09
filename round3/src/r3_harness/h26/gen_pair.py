"""Paired-world generator (PROT-H26 B2): low-equivalence is validated by the ORACLE before any variant runs; invalid
draws are re-drawn (bounded 50 tries, counted), then the pair is skipped and counted. Never raises."""
from __future__ import annotations

import copy
import json
import random
from pathlib import Path

from r3_oracle import ops_model
from r3_oracle.disclosure import Facts, low_view
from r3_oracle.disclosure_prov import decision_low
from r3_oracle.disclosure_reads import canaries_of
from r3_shared.governance import load_governance

from . import gen_vary as V, invariants, sim
from .gen_auth import perturb
from .gen_plan import build_plan

ROUND3 = Path(__file__).resolve().parents[3]
DOMAINS = ("manufacturing", "project")
CYCLE = ("F", "E", "L", "D", "C", "G", "M")
MAX_TRIES = 50
_cache: dict = {}


def load(domain: str):
    if domain not in _cache:
        ops = json.loads((ROUND3 / f"spec/ops/{domain}.json").read_text())
        au = json.loads((ROUND3 / f"spec/authority/{domain}.v3.json").read_text())
        _cache[domain] = (ops, au, load_governance("hierarchical", domain))
    return copy.deepcopy(_cache[domain][0]), copy.deepcopy(_cache[domain][1]), copy.deepcopy(_cache[domain][2])


def _snap_after(base: dict, delta: dict, ops, auth, nows=0):
    s = sim.apply_changes(base, [c for b in delta["batches"] for c in b])
    for h in delta["high"]:
        o = ops_model.evaluate(ops, auth, h["actor"], None, h["op"], h["args"], s, nows, frozenset(), None)
        if o.commits:
            s = sim.apply_effects(s, o.effects)
    return s


def row_schedule(base: dict, delta: dict, ops, auth, nows=0) -> list:
    """G3-E32(b): world_log rows appended per phase (each seed batch, then each hidden op incl. commit flag)."""
    out, s = [], base
    for b in delta["batches"]:
        out.append(("batch", sim.change_rows(s, b)))
        s = sim.apply_changes(s, b)
    for h in delta["high"]:
        o = ops_model.evaluate(ops, auth, h["actor"], None, h["op"], h["args"], s, nows, frozenset(), None)
        out.append(("high", bool(o.commits), sim.effect_rows(s, o.effects) if o.commits else 0))
        if o.commits:
            s = sim.apply_effects(s, o.effects)
    return out


def _facts(delta: dict, info: dict) -> Facts:
    f = Facts()
    f.edges = [dict(e) for e in delta["edges"]]
    for c in delta["cases"]:
        if "G" in info:
            f.cases[c["action"]["case"]] = {"requester": c["actor"], "members": info["G"]["members"], "state": None}
    return f


def one(seed: int, idx: int, kind: str | None = None, domain: str | None = None, aa: bool = False):
    """Return (pair | None, stats). pair None = skipped after MAX_TRIES (stats counts it)."""
    kind = kind or CYCLE[idx % len(CYCLE)]
    domain = domain or DOMAINS[idx % 2]
    stats = {"redraws": 0, "d4_attempted": 0, "d4_replaced": 0, "skipped": 0, "invariant_redraws": 0}
    if kind in ("L", "F") and not V.kind_feasible(load(domain)[0], kind):  # G3-E30: no reachable variation of this kind here
        stats["kind_substituted"] = f"{kind}->E"
        kind = "E"
    for attempt in range(MAX_TRIES):
        rng = random.Random(f"{seed}:{idx}:{attempt}")
        p = _try(rng, seed, idx, kind, domain, stats, aa)
        if p is not None:
            return p, stats
        stats["redraws"] += 1
    stats["skipped"] = 1
    return None, stats


def _try(rng, seed, idx, kind, domain, stats, aa):
    ops, base_auth, gov = load(domain)
    auth = perturb(rng, ops, base_auth, f"{idx}")
    observer = rng.choice([p["id"] for p in auth["principals"] if p["delegated_by"] is None])
    base = sim.apply_changes(sim.empty(), [c for b in sim.seed_batches(ops) for c in b])
    lv0 = low_view(base, auth, observer, ops)
    pool = [k for k in V.KINDS if V.kind_feasible(ops, k)]
    kinds = [kind] if kind != "M" else rng.sample(pool, rng.randint(2, 4))
    d1, d2, info = V.empty(), V.empty(), {}
    for k in kinds:
        n = f"{idx}{k}"
        r = {"F": lambda: V.vary_F(rng, ops, lv0, base), "E": lambda: V.vary_E(rng, ops, lv0, base),
             "L": lambda: V.vary_L(rng, ops, lv0, base), "D": lambda: V.vary_D(rng, ops, auth, lv0, base, observer, n),
             "C": lambda: V.vary_C(rng, ops, auth, lv0, base, observer, n),
             "G": lambda: V.vary_G(rng, ops, auth, gov, observer, n, base)}[k]()
        if r is None:
            return None
        a, b, inf = r
        for d, x in ((d1, a), (d2, b)):
            for f in ("batches", "high", "edges", "cases"):
                d[f] += x[f]
        info[k] = inf
    if aa:  # A/A control: the same world twice
        d2 = copy.deepcopy(d1)
    s = [_snap_after(base, d, ops, auth) for d in (d1, d2)]
    if any(invariants.violations(ops, si) for si in s):  # G3-E28: both predicted worlds must be reachable states
        stats["invariant_redraws"] = stats.get("invariant_redraws", 0) + 1
        return None
    sched = [row_schedule(base, d, ops, auth) for d in (d1, d2)]
    if sched[0] != sched[1]:  # G3-E32(b): equal world_log schedule in every phase, or re-draw
        stats["schedule_redraws"] = stats.get("schedule_redraws", 0) + 1
        return None
    facts = [_facts(d, info) for d in (d1, d2)]
    lvs = [low_view(si, auth, observer, ops, f) for si, f in zip(s, facts)]
    if lvs[0].to_doc() != lvs[1].to_doc():
        return None
    swap = info.get("D", {}).get("mode") in ("swap", "valdiff")
    for h in d1["high"]:  # "args"-mode decisions must stay hidden; "swap"-mode decisions are meant to be visible (actors redacted)
        opd = ops_model.op_of(ops, h["op"])
        vis = any(f"{t}:{k_}" in lvs[0].objects for t, k_ in ops_model.resources_of(opd, h["args"]))
        if vis and not swap:
            return None
    if info.get("D", {}).get("mode") == "valdiff":  # G3-fix9: a valdiff decision may differ only in invisible resources or scalar values
        h1, h2 = d1["high"][0], d2["high"][0]
        opd = ops_model.op_of(ops, h1["op"])
        r1, r2 = ops_model.resources_of(opd, h1["args"]), ops_model.resources_of(opd, h2["args"])
        if any(a != b and (f"{a[0]}:{a[1]}" in lvs[0].objects or f"{b[0]}:{b[1]}" in lvs[0].objects)
               for a, b in zip(sorted(r1), sorted(r2))):
            stats["valdiff_redraws"] = stats.get("valdiff_redraws", 0) + 1
            return None
    differ = (s[0]["objects"] != s[1]["objects"] or s[0]["links"] != s[1]["links"] or d1["edges"] != d2["edges"]
              or d1["cases"] != d2["cases"] or d1["high"] != d2["high"])
    if not aa and not differ:
        return None
    hidden_refs = [r_ for i_ in info.values() for r_ in ([i_.get("ref")] if i_.get("ref") else []) + i_.get("keys", []) + i_.get("dsts", [])]
    own_rids: list = []
    hid_rids = [h["rid"] for h in d1["high"]]
    if swap:
        info["D"]["visible"] = True
    hid_edges = [e["id"] for e in d1["edges"]]
    hid_cases = [c["action"]["case"] for c in d1["cases"]]
    plan, tried, repl = build_plan(rng, ops, auth, observer, s, hidden_refs, own_rids, hid_rids, hid_edges, hid_cases,
                                   gov=gov if "G" in kinds else None)
    stats["d4_attempted"] += tried
    stats["d4_replaced"] += repl
    canaries = sorted(canaries_of([s[0], s[1], d1, d2, info]), key=str)
    return {"id": f"p{seed}-{idx}{'-aa' if aa else ''}", "domain": domain, "seed": seed, "idx": idx, "observer": observer,
            "auth": auth, "kinds": kinds, "info": info, "w": [d1, d2], "plan": plan, "canaries": canaries, "aa": aa,
            "governance": gov if "G" in kinds else None, "own_rids": own_rids,
            "predicted_doc_sha": __import__("hashlib").sha256(json.dumps(lvs[0].to_doc(), sort_keys=True).encode()).hexdigest()}


def draw(seed: int, idx: int, **kw):
    try:
        return one(seed, idx, **kw)
    except Exception as exc:  # noqa: BLE001 - generators never raise (counted)
        return None, {"redraws": 0, "d4_attempted": 0, "d4_replaced": 0, "skipped": 1, "gen_error": f"{type(exc).__name__}: {exc}"}


_ = decision_low
