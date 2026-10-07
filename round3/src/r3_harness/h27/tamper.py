"""B3 tamper corpus: the frozen classes composed ONLY from TamperView primitives (list/read/write/delete/rename).
The affected set is derived from the END STATE of the store versus the base history (what actually changed), never from
which primitive was meant: definite = envelope record changed/missing or a bound artifact no longer present by content;
indeterminate = later decisions whose own bytes are untouched but whose predecessor chain changed (a verifier may
verify them through anchor roots only), or whose bound artifact survives only under a different key; either answer is
acceptable for these and neither is counted (R27-3 still applies: a VERIFIED answer must return the bound artifacts)."""
from __future__ import annotations

import copy
import json
import re

from r3_oracle import provenance as pv

from . import layout

CLASSES = ("T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9")
SINGLE = ("T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8")


def _leaves(x, path=()):
    if isinstance(x, dict):
        for k, v in x.items():
            yield from _leaves(v, path + (k,))
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from _leaves(v, path + (i,))
    else:
        yield path, x


def _flip(v):
    if isinstance(v, bool):
        return not v
    if isinstance(v, int):
        return v + 1
    if isinstance(v, str):
        return v + "~"
    return "x"


def _put(view, sc, seq, env) -> None:
    for h in sc.envs.get(seq, []):
        rec = json.loads(view.read(h["key"]))
        view.write(h["key"], pv.canon(pv.set_nested(rec, h["path"], env)))


def relink(view, base, from_seq: int, new_envs: dict | None = None) -> dict[int, str]:
    """Recompute prev links (and roots) from `from_seq` on, writing only envelopes that change. Returns seq -> new root."""
    sc = layout.scan(view)
    roots, new_envs = {}, new_envs or {}
    prev = pv.root_of(sc.env(from_seq - 1)) if from_seq > 1 and sc.env(from_seq - 1) else pv.ZERO
    for seq in range(from_seq, base.n + 1):
        env = copy.deepcopy(new_envs.get(seq) or sc.env(seq))
        if env is None:
            continue
        env["seq"], env["prev"] = seq, prev
        if env != sc.env(seq):
            _put(view, sc, seq, env)
        roots[seq] = prev = pv.root_of(env)
    return roots


def t1(view, base, rng, ctx) -> bool:
    sc = layout.scan(view)
    if rng.random() < 0.5:
        s = rng.randint(1, base.n)
        kind, d = rng.choice(base.bound(s))
        holders = sc.holders(d)
        if not holders:
            return False
        try:
            obj = json.loads(sc.raw[holders[0]])
            lv = [p for p, v in _leaves(obj) if p]
            new = None
            if lv:
                path = lv[rng.randrange(len(lv))]
                cur = obj
                for k in path[:-1]:
                    cur = cur[k]
                cur[path[-1]] = _flip(cur[path[-1]])
                new = pv.canon(obj)
        except (ValueError, TypeError):
            new = None
        new = new or b"{}"
        for k in holders:
            view.write(k, new)
        ctx["flags"].add(f"mutate:{kind}")
        return True
    m = rng.randint(1, base.n)
    hits = sc.envs.get(m)
    if not hits:
        return False
    env = copy.deepcopy(hits[0]["env"])
    leaves = [p for p, _ in _leaves(env) if p and p[0] not in ("v",)]
    if not leaves:  # nothing flippable in this envelope: a recorded no-op attempt, never an exception
        return False
    path = rng.choice(leaves)
    cur = env
    for k in path[:-1]:
        cur = cur[k]
    cur[path[-1]] = _flip(cur[path[-1]])
    _put(view, sc, m, env)
    ctx["flags"].add("mutate:envelope")
    return True


def t2(view, base, rng, ctx) -> bool:
    sc = layout.scan(view)
    s = rng.randint(1, base.n)
    kind, d = rng.choice(base.bound(s))
    holders = sc.holders(d)
    for k in holders:
        view.delete(k)
    if holders:
        ctx["flags"].add(f"delete:{kind}")
    return bool(holders)


def t3(view, base, rng, ctx) -> bool:
    sc = layout.scan(view)
    m = rng.randint(1, base.n)
    keys = {h["key"] for h in sc.envs.get(m, [])}
    for k in keys:
        view.delete(k)
    return bool(keys)


def t4(view, base, rng, ctx) -> bool:
    sc = layout.scan(view)
    s = rng.randint(1, base.n)
    kind, d = rng.choice(base.bound(s))
    pool = sorted({x for q in range(1, base.n + 1) for kk, x in base.bound(q) if kk == kind and x != d})
    holders = sc.holders(d)
    if not pool or not holders:
        return False
    other = base.blob_bytes(rng.choice(pool))
    for k in holders:
        view.write(k, other)
    ctx["flags"].add(f"substitute:{kind}")
    return True


def _similar(base, kind, d, rng):
    blob = base.blob_bytes(d)
    cands = []
    for x in sorted(base.all_digests() - {d}):
        b = base.blob_bytes(x)
        if kind == "evidence":
            try:
                a, c = json.loads(blob), json.loads(b)
            except (ValueError, TypeError):
                continue
            if isinstance(a, dict) and isinstance(c, dict) and a.get("ref") == c.get("ref") and "version" in c:
                cands.append(x)
        elif any(kk == kind and dd == x for q in range(1, base.n + 1) for kk, dd in base.bound(q)):
            cands.append(x)
    return rng.choice(cands) if cands else None


def t5(view, base, rng, ctx) -> bool:
    for _ in range(12):
        s = rng.randint(1, base.n)
        kind, d = rng.choice(base.bound(s))
        d2 = _similar(base, kind, d, rng)
        if d2 is None or not base.sc.holders(d2):
            continue
        n = 0
        for k in view.keys(""):
            raw = view.read(k)
            if d.encode() in raw and pv.sha(raw) != d:
                view.write(k, raw.replace(d.encode(), d2.encode()))
                n += 1
        if n:
            relink(view, base, s + 1)
            ctx["flags"].add(f"rebind:{kind}")
            return True
    return False


def t6(view, base, rng, ctx) -> bool:
    if base.n < 2:
        return False
    sc = layout.scan(view)
    i, j = sorted(rng.sample(range(1, base.n + 1), 2))
    ei, ej = sc.env(i), sc.env(j)
    if ei is None or ej is None:
        return False
    relink(view, base, i, {i: ej, j: ei})
    ctx["flags"].add("reorder")
    return True


def t7(view, base, rng, ctx) -> bool:
    sc = layout.scan(view)
    k = rng.randint(1, max(1, min(3, base.n - 1)))
    ok = False
    for m in range(base.n - k + 1, base.n + 1):
        for h in sc.envs.get(m, []):
            view.delete(h["key"])
            ok = True
    return ok


def t8(view, base, rng, ctx) -> bool:
    before = {s: pv.root_of(e) for s in range(1, base.n + 1) if (e := layout.scan(view).env(s))}
    if not (t5 if rng.random() < 0.5 else t6)(view, base, rng, ctx):
        return False
    sc = layout.scan(view)
    for s, hits in sc.receipts.items():
        env = sc.env(s)
        if env is None or before.get(s) == pv.root_of(env):
            continue
        for h in hits:
            ent = dict(h["entry"], root=pv.root_of(env), decision_id=env["decision"].get("decision_id"))
            rec = json.loads(view.read(h["key"]))
            view.write(h["key"], pv.canon(pv.set_nested(rec, h["path"], ent)))
    ctx["flags"].add("forge")
    return True


def t9(view, base, rng, ctx) -> bool:
    """Continuation: delete the idempotency record of a committed request_id and resurrect a consumed approval record."""
    lay = base.stream.layout
    if "idempotency" not in lay or "approval" not in lay:
        ctx["unsupported"] = "layout lacks idempotency/approval kinds"
        return False
    done = [d for d in base.decisions if d["kind"] in ("call_tool", "direct") and d["status"] == "OK" and d["rows"]]
    if not done:
        return False
    x = rng.choice(done)
    rid = x["request_id"]
    for k in view.keys(lay["idempotency"]):
        if rid in k or rid.encode() in (view.read(k) or b""):
            view.delete(k)
    ctx["resend"] = {"request_id": rid, "kind": x["kind"], "subject": x["subject"], "operation": x["operation"],
                     "args": x["args"], "obo": x["obo"]}
    for i, d in enumerate(base.decisions):  # a consumed approval: approve record followed by its commit
        if d["kind"] == "approve" and d.get("approval_records"):
            nxt = next((c for c in base.decisions[i + 1:] if c["kind"] in ("call_tool", "direct") and c["status"] == "OK"
                        and c["operation"] == d["operation"] and c["args"] == d["args"] and c["subject"] == d["requester"]), None)
            if nxt:
                for k, v in d["approval_records"].items():
                    view.write(k, v)
                ctx["approval_req"] = {"kind": nxt["kind"], "subject": nxt["subject"], "operation": nxt["operation"],
                                       "args": nxt["args"], "obo": nxt["obo"]}
                break
    ctx["flags"].add("continuation")
    return True


APPLY = {"T1": t1, "T2": t2, "T3": t3, "T4": t4, "T5": t5, "T6": t6, "T7": t7, "T8": t8, "T9": t9}


def apply_case(view, base, rng, classes: list[str]) -> dict:
    ctx = {"flags": set(), "classes": list(classes), "applied": []}
    for c in classes:
        if APPLY[c](view, base, rng, ctx):
            ctx["applied"].append(c)
    return ctx


_SEQ = re.compile(r"(?:^|/)(\d+)$")
# layout kinds whose records are not part of a decision's bound state (request/approval ledgers, stream meta): T9 owns them
_LEDGER_KINDS = ("approval", "idempotency", "ledger_meta", "meta", "stream")


def holders_of_bound(base) -> dict[int, list[str]]:
    """seq -> keys of ORIGINAL records (not envelopes/receipts/artifact blobs) that carry one of that decision's bound
    digests as text (sidecars, indexes; found by content, never by layout). A key ending in a seq number belongs to that
    seq only (a digest shared by many decisions must not make every sidecar everyone's), other keys to every match."""
    cached = getattr(base, "_bound_holders", None)
    if cached is not None:
        return cached
    sc, skip, out = base.sc, set(), {}
    lay = base.stream.layout
    ledger = tuple(lay[k] for k in _LEDGER_KINDS if lay.get(k))
    for hits in list(sc.envs.values()) + list(sc.receipts.values()):
        skip.update(h["key"] for h in hits)
    blobs = base.all_digests()
    for k, raw in sc.raw.items():
        if k in skip or pv.sha(raw) in blobs or (ledger and k.startswith(ledger)):
            continue
        m = _SEQ.search(k)
        kseq = int(m.group(1)) if m else None
        for s in range(1, base.n + 1):
            if kseq is not None and kseq != s:
                continue
            if any(d.encode() in raw for _, d in base.bound(s)):
                out.setdefault(s, []).append(k)
    base._bound_holders = out
    return out


def derive(base, view) -> dict:
    """definite / indeterminate / unaffected seq sets from the end state of the store (see module docstring)."""
    sc = layout.scan(view)
    present = layout.digests_present(sc, base.all_digests())
    definite, changed, moved = set(), set(), set()
    for s in range(1, base.n + 1):
        orig = base.sc.envs.get(s, [])
        ch = not orig
        for h in orig:
            raw = sc.raw.get(h["key"])
            try:
                ch = ch or raw is None or json.loads(raw) != h["record"]
            except ValueError:
                ch = True
        if ch:
            changed.add(s)
            definite.add(s)
        for k in holders_of_bound(base).get(s, []):  # a record holding its bound digests (sidecar) changed/vanished
            if sc.raw.get(k) != base.sc.raw.get(k):
                definite.add(s)
        if any(not present[d] for _, d in base.bound(s)):
            definite.add(s)
        elif any(not set(sc.blobs[d]) & set(base.sc.blobs.get(d, [])) for _, d in base.bound(s)):
            moved.add(s)  # the bytes survive only under another key: content-addressed lookups may find them, key lookups not
    first = min(changed) if changed else None
    indet = {s for s in range(1, base.n + 1) if first is not None and s > first and s not in definite} | (moved - definite)
    missing = {s: [k for k, d in base.bound(s) if not present[d]] for s in definite}
    return {"definite": definite, "indeterminate": indet, "changed_env": changed,
            "unaffected": set(range(1, base.n + 1)) - definite - indet, "missing": missing}
