"""Run one world of a pair: seed -> deploy -> subscribe -> high phase -> observation plan. Returns a Run record with the
canonical observations (oracle-owned projection) and the per-observation oracle judgements."""
from __future__ import annotations

import copy
import time

from r3_oracle import lowproj
from r3_oracle.disclosure import Facts
from r3_oracle.disclosure_reads import canaries_of
from r3_shared.variant import g3_call, g2_call

from . import judge, sim
from .env import PWorld


def _call(fn):
    """(result | None, label | None): NotImplementedError -> unsupported; any other exception -> variant_error."""
    try:
        return fn(), None
    except NotImplementedError as e:
        return None, ("unsupported", str(e)[:80])
    except Exception as e:  # noqa: BLE001
        return None, ("variant_error", type(e).__name__)


def run_world(variant, pair: dict, wi: int, tag: str = "w") -> dict:
    from .gen_pair import load
    ops, _b, _g = load(pair["domain"])
    d = pair["w"][wi]
    auth, obs_id = pair["auth"], pair["observer"]
    w = PWorld(variant, pair["domain"], ops, auth, sim.seed_batches(ops) + d["batches"], pair["governance"], tag)
    run = {"obs": [], "rows": [], "tags": [], "labels": [], "facts": {}, "lat": []}
    try:
        tok = w.token(obs_id)
        rn = lowproj.Renamer()
        sub_id = None

        def record(i, item, res, label, lat=0.0):
            m = item["m"]
            if res is None:
                run["labels"].append(label[0])
                run["obs"].append(lowproj.canonical_label(m, label[0]) if hasattr(lowproj, "canonical_label") else
                                  f"{m}:{label[0]}".encode())
                run["rows"].append({"i": i, "m": m, "status": label[0], "body": {}})
                return
            run["obs"].append(lowproj.project_result(m, res, rn))
            run["rows"].append({"i": i, "m": m, "status": res.status, "body": res.body})
            run["lat"].append(lat)

        # observer subscribes before the high phase (events then cover it)
        types = [t["name"] for t in ops["resource_types"]]
        r, lab = _call(lambda: g3_call(w.dep, "subscribe", tok, {"types": types}))
        record(-1, {"m": "subscribe"}, r, lab)
        if r is not None and r.status == "OK":
            sub_id = r.body.get("sub")
        for h in d["high"]:
            w.request(h["actor"], h["op"], copy.deepcopy(h["args"]), h["rid"])
        for e in d["edges"]:
            res, lab = _call(lambda: g2_call(w.dep, "delegate", w.token(e["issuer"]), copy.deepcopy(e), f"hd-{e['id']}"))
            if res is not None and res.status == "OK":
                w.facts.edges.append(dict(e))
        for c in d["cases"]:
            res, lab = _call(lambda: g3_call(w.dep, "constitutional", w.token(c["actor"]), copy.deepcopy(c["action"]), c["rid"]))
            if res is not None and res.status == "OK":
                w.facts.cases[c["action"]["case"]] = {"requester": c["actor"], "state": None,
                                                      "members": sorted({m for b in (pair["governance"] or {"bodies": []})["bodies"] for m in b["members"]})}
        w.clock.advance(1)
        for i, item in enumerate(pair["plan"]):
            _step(w, pair, tok, sub_id, i, item, record, run)
        run["facts"] = {"decisions": len(w.facts.decisions), "edges": len(w.facts.edges), "cases": len(w.facts.cases)}
    finally:
        w.close()
    return run


def _step(w, pair, tok, sub_id, i, item, record, run):
    m, obs_id = item["m"], pair["observer"]
    lv = w.view(obs_id)
    prot = set(pair["canaries"]) - canaries_of(lv.to_doc())
    t0 = time.perf_counter()
    res = lab = None
    if m == "tools":
        res0, lab = _call(lambda: w.dep.tools(tok))
        if res0 is None:
            return record(i, item, None, lab)
        j = judge.judge_tools(lv, res0, w.auth, w.ops, w.facts.edges)
        run["tags"] += [(i, m, f"{k}") for k, v in j.items() if v for _ in v[:1]]
        run["tags"] += [(i, m, "exposure_ok")] if not any(j.values()) else []
        body = lowproj.project_tools(res0)
        run["obs"].append(body)
        run["rows"].append({"i": i, "m": m, "status": "TOOLS", "body": {"names": sorted(t.name for t in res0)}})
        if prot & canaries_of([{"n": t.name, "s": t.input_schema} for t in res0]):
            run["tags"].append((i, m, "value_exfiltration"))
        return
    if m == "mutate":
        res, exc, eff, out = w.request(obs_id, item["op"], copy.deepcopy(item["args"]), item["rid"], item["via"])
        lab = exc
        if res is not None and item["kind"] == "unauth" and eff and not out.commits:
            run["tags"].append((i, m, "forbidden_effect"))
        if res is not None and item["kind"] == "d4":
            run["tags"].append((i, m, "d4_ok" if (res.status == "OK") == out.commits else "progress_loss"))
        return record(i, item, res, lab, (time.perf_counter() - t0) * 1000)
    call = {"read_object": lambda: g3_call(w.dep, "read_object", tok, item.get("ref")),
            "list_objects": lambda: g3_call(w.dep, "list_objects", tok, item.get("type")),
            "list_links": lambda: g3_call(w.dep, "list_links", tok, item.get("ref"), item.get("lt")),
            "query": lambda: g3_call(w.dep, "query", tok, item["name"], copy.deepcopy(item["args"])),
            "poll": lambda: g3_call(w.dep, "poll", tok, sub_id),
            "prov_decision": lambda: g3_call(w.dep, "prov_decision", tok, item["id"]),
            "prov_object": lambda: g3_call(w.dep, "prov_object", tok, item["ref"]),
            "authority_used_as": lambda: g3_call(w.dep, "authority_used_as", tok, item["rid"]),
            "delegate": lambda: g2_call(w.dep, "delegate", tok, copy.deepcopy(item["edge"]), item["rid"]),
            "revoke": lambda: g2_call(w.dep, "revoke", tok, item["edge_id"], item["rid"]),
            "constitutional": lambda: g3_call(w.dep, "constitutional", tok, copy.deepcopy(item["action"]), item["rid"])}[m]
    res, lab = _call(call)
    record(i, item, res, lab, (time.perf_counter() - t0) * 1000)
    if res is None:
        return
    if prot & canaries_of(res.body):
        run["tags"].append((i, m, "value_exfiltration"))
    if m in judge.READ_M:
        mm = judge.judge_read(lv, item, res)
        run["tags"].append((i, m, "read_ok" if mm is False else "read_mismatch" if mm else "read_unjudged"))
    if m in ("read_object", "list_objects", "list_links", "query", "poll", "prov_decision", "prov_object", "authority_used_as"):
        bad = judge.form_ok(m, res)
        if bad:
            run["tags"].append((i, m, "form_violation"))
    if m in ("prov_decision", "prov_object", "authority_used_as"):
        tags = judge.judge_prov(lv, item, res)
        run["tags"] += [(i, m, t) for t in tags] or [(i, m, "prov_ok")]
