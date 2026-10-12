"""End of a sequence: the shared world's record (commit marks, final snapshot) and the per-deployment slices of the three service logs,
all with RELATIVE ticks. The ledger and the anchor log themselves are read by the judge after the services close (keys revealed)."""
from __future__ import annotations

from r3_shared.world import WorldReader


def _rel(rows, base, keys=("tick", "from_tick", "to_tick", "granted_tick", "lease_until", "requested_tick", "effective_tick")):
    out = []
    for x in rows:
        y = dict(x)
        for k in keys:
            if isinstance(y.get(k), int):
                y[k] = y[k] - base
        out.append(y)
    return out


def finish(r) -> None:
    from . import services
    rec, base = r.rec, r.base
    r.stream = r.stream or services.stream_of(r.hist_path)
    try:
        rd = WorldReader(r.world_path)
        try:
            log, snap = rd.log(), rd.snapshot()
        finally:
            rd.close()
        rec["world"] = {"marks": [{"seq": x["seq"], "tick": x["tick"] - base, "data": x["data"], "writer": x["writer"]} for x in log
                                  if x["kind"] == "mark" and x["ref"] == "commit"],
                        "rows": len(log), "objects": {k: v["props"] for k, v in snap["objects"].items()}, "links": snap["links"]}
    except Exception as exc:  # noqa: BLE001 - B4 deletes the store on purpose
        rec["world"] = None
        rec["world_error"] = f"{type(exc).__name__}: {exc}"[:200]
    deps = {r.dep, r.dep + "~rc1b"}
    try:
        lg = r.svc.auth.log()
        ver = [{k: v for k, v in x.items() if k not in ("doc_json", "doc", "seq")} for x in lg["versions"] if x["requested_tick"] >= base]
        for n, v in enumerate(ver, 1):
            v["seq"] = n                                   # renumbered: service-global seq / MACs differ per service instance and worker
        drop = lambda rows: [{k: v for k, v in x.items() if k not in ("seq", "mac")} for x in rows if x["deployment"] in deps]  # noqa: E731
        rec["auth"] = {"versions": _rel(ver, base), "leases": _rel(drop(lg["leases"]), base),
                       "faults": _rel(drop(lg["faults"]), base), "refused": _rel(drop(lg["refused"]), base)}
    except Exception as exc:  # noqa: BLE001
        rec["auth"] = None
        r.harness_row("service_log_unavailable", service="auth", detail=str(exc)[:120])
    try:
        fl = r.svc.anchor_ctl.fault_log()
        st = r.stream
        rec["anchor"] = {"stream": st, "windows": _rel([w for w in fl["windows"] if w.get("deployment") == st], base),
                         "log": _rel([x for x in fl["log"] if x.get("stream") == st], base)}   # activations: tick/op/mode/applied
    except Exception as exc:  # noqa: BLE001
        rec["anchor"] = None
        r.harness_row("service_log_unavailable", service="anchor", detail=str(exc)[:120])
    try:
        rec["ext"] = _rel([{k: v for k, v in x.items() if k not in ("seq",)} for x in r.svc.ext.fault_log() if x.get("deployment") in deps], base)
    except Exception as exc:  # noqa: BLE001
        rec["ext"] = None
        r.harness_row("service_log_unavailable", service="ext", detail=str(exc)[:120])
    rec["kills"] = [dict(k) for k in r.kills]
    rec["obs_windows"] = [dict(w) for w in r.obs_windows]
    rec["faults"] = {k: dict(v) for k, v in r.faults.items()}
    rec["end_tick"] = r.t
    rec["stream"] = r.stream or None
