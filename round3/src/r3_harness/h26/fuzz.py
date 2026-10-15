"""Exfiltration fuzz (ORACLE-AND-HARNESS-G3 B3): single world, hidden-key dictionary, mutated args; canary scan of every
response and identifier twins (hidden ref vs never-existing ref of the same shape, probe key replaced by "<probe>")."""
from __future__ import annotations

import copy
import json
import random

from r3_oracle.disclosure_reads import canaries_of
from r3_shared.variant import g2_call, g3_call

from . import gen_pair, sim
from .env import PWorld
from .gen_vary import canary_key
from .observe import _call

JUNK = ["", " ", "A" * 300, "../x", "'; --", "Part:", ":", "null", "\u0000", "T:" + "k" * 200]
CALLS_PER_WORLD = 100


def _norm(res, keys) -> str:
    s = json.dumps([res.status, res.body], sort_keys=True)
    for k in keys:
        if isinstance(k, str) and len(k) >= 6:
            s = s.replace(k, "<probe>")
    return s


def _world(variant, pair):
    from .gen_pair import load
    ops, _b, _g = load(pair["domain"])
    d = pair["w"][0]
    w = PWorld(variant, pair["domain"], ops, pair["auth"], sim.seed_batches(ops) + d["batches"], pair["governance"], "fz")
    for h in d["high"]:
        w.request(h["actor"], h["op"], copy.deepcopy(h["args"]), h["rid"])
    for e in d["edges"]:
        res, _l = _call(lambda: g2_call(w.dep, "delegate", w.token(e["issuer"]), copy.deepcopy(e), f"hd-{e['id']}"))
        if res is not None and res.status == "OK":
            w.facts.edges.append(dict(e))
    for c in d["cases"]:
        res, _l = _call(lambda: g3_call(w.dep, "constitutional", w.token(c["actor"]), copy.deepcopy(c["action"]), c["rid"]))
        if res is not None and res.status == "OK":
            w.facts.cases[c["action"]["case"]] = {"requester": c["actor"], "state": None, "members": sorted(
                {m for b in (pair["governance"] or {"bodies": []})["bodies"] for m in b["members"]})}
    w.clock.advance(1)
    return w, ops


def run(variant, seed: int, n_calls: int) -> dict:
    out = {"calls": 0, "worlds": 0, "value_exfiltration": [], "existence_leak": [], "twin_checks": 0, "variant_error": 0,
           "unsupported": 0, "form_violation": 0, "per_method": {}}
    j = 0
    while out["calls"] < n_calls and j < 40 + n_calls // 10:
        pair, _st = gen_pair.draw(seed + 777, j)
        j += 1
        if pair is None:
            continue
        rng = random.Random(f"fz:{seed}:{j}")
        w, ops = _world(variant, pair)
        try:
            out["worlds"] += 1
            _fuzz_world(w, ops, pair, rng, out, min(CALLS_PER_WORLD, n_calls - out["calls"]))
        finally:
            w.close()
    return out


def _fuzz_world(w, ops, pair, rng, out, n):
    obs = pair["observer"]
    tok = w.token(obs)
    types = [t["name"] for t in ops["resource_types"]]
    lts = [l["name"] for l in ops["link_types"]]
    for c in range(n):
        lv = w.view(obs)
        prot = set(pair["canaries"]) - canaries_of(lv.to_doc())
        snap = w.snapshot()
        hidden = sorted(r for r in snap["objects"] if r not in lv.objects) or [f"{types[0]}:none"]
        hid_ids = [d["id"] for d in w.facts.decisions if d["id"] not in lv.to_doc()["decisions"]] or ["hid-0"]
        kind = rng.choice(["read_object", "list_objects", "list_links", "query", "prov_decision", "prov_object",
                           "authority_used_as", "mutate", "revoke", "constitutional", "poll", "junk"])
        ref = rng.choice(hidden + JUNK[:4])
        t = ref.split(":", 1)[0] if ":" in ref else types[0]
        twin = f"{t}:{canary_key(rng)}"
        is_h = ref in hidden
        req_vals = [ref, twin]  # G3-E28: values the observer itself sent are not exfiltration
        if kind == "mutate":
            op = rng.choice(ops["operations"])
            res_in = [i for i in op["inputs"] if i["type"] == "resource"]
            args = {i["name"]: (ref.split(":", 1)[1] if ":" in ref else "x") if i["type"] == "resource" else rng.choice([1, "s", None, [], {"a": 1}])
                    for i in op["inputs"]}
            targs = {k: (twin.split(":", 1)[1] if v == (ref.split(":", 1)[1] if ":" in ref else "x") else v) for k, v in args.items()}
            req_vals += [args, targs]
            a, b = [w.request(obs, op["name"], x, f"fz-{c}-{n_}", rng.choice(["direct"]))[0] for n_, x in enumerate((args, targs))]
            pair_res = (a, b) if res_in else None
            if pair_res and is_h and a is not None and b is not None:
                out["twin_checks"] += 1
                if _norm(a, [ref.split(":", 1)[-1]]) != _norm(b, [twin.split(":", 1)[-1]]):
                    out["existence_leak"].append({"m": "mutate", "op": op["name"], "a": _norm(a, [ref.split(":", 1)[-1]]), "b": _norm(b, [twin.split(":", 1)[-1]])})
            res = a
        else:
            def mk(r, did, eid, cid):
                return {"read_object": lambda: g3_call(w.dep, "read_object", tok, r),
                        "list_objects": lambda: g3_call(w.dep, "list_objects", tok, rng.choice(types + JUNK[:2]) if r is None else t),
                        "list_links": lambda: g3_call(w.dep, "list_links", tok, r, rng.choice(lts)),
                        "query": lambda: g3_call(w.dep, "query", tok, rng.choice([x["name"] for x in ops["reads"]] + JUNK[:2]), {"x": r}),
                        "prov_decision": lambda: g3_call(w.dep, "prov_decision", tok, did),
                        "prov_object": lambda: g3_call(w.dep, "prov_object", tok, r),
                        "authority_used_as": lambda: g3_call(w.dep, "authority_used_as", tok, did),
                        "revoke": lambda: g2_call(w.dep, "revoke", tok, eid, f"fz-rv-{c}"),
                        "constitutional": lambda: g3_call(w.dep, "constitutional", tok, {"kind": "judge", "case": cid, "stage": "decision", "value": "concur", "merit": "m"}, f"fz-cj-{c}"),
                        "poll": lambda: g3_call(w.dep, "poll", tok, rng.choice(["sub-1", "nope"])),
                        "junk": lambda: g3_call(w.dep, "read_object", tok, rng.choice([None, 5, [], {}]))}[kind]
            did, eid, cid = rng.choice(hid_ids), (w.facts.edges[0]["id"] if w.facts.edges else "hedge-0"), (next(iter(w.facts.cases), "hcase-0"))
            sd = rng.getrandbits(32)
            req_vals += [did, eid, cid]
            tw = (f"nope-{sd:08x}", f"nope-e-{sd:08x}", f"nope-c-{sd:08x}")
            req_vals += list(tw)
            state = rng.getstate()
            res, lab = _call(mk(ref, did, eid, cid))
            rng.setstate(state)
            res2, lab2 = _call(mk(twin, tw[0], tw[1], tw[2]))
            if lab or lab2:
                out["unsupported" if (lab or lab2)[0] == "unsupported" else "variant_error"] += 1
            elif kind not in ("junk", "poll", "list_objects", "query") and (is_h or kind in ("prov_decision", "authority_used_as", "revoke", "constitutional")):
                out["twin_checks"] += 1
                ids = [x.split(":", 1)[-1] for x in (ref, did, eid, cid)] + [x.split(":", 1)[-1] for x in (twin,) + tw]
                if _norm(res, ids[:4]) != _norm(res2, ids[4:]):
                    out["existence_leak"].append({"m": kind, "a": _norm(res, ids[:4]), "b": _norm(res2, ids[4:])})
        out["calls"] += 1
        out["per_method"][kind] = out["per_method"].get(kind, 0) + 1
        if res is not None and (prot - canaries_of(req_vals)) & canaries_of(res.body):
            out["value_exfiltration"].append({"m": kind})
