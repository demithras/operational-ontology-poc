"""Fault injection through the SERVER-SIDE control planes only (P1g-3, G5-E6): AuthorityService outage/partition, AnchorServer
partition(stream), ExternalWorld outage/partition(system), and the OBS gate (observer symlink). Adapters and variants never hold a
control socket. The service logs are the independent record of what was enforced (invalid_if a)."""
from __future__ import annotations

from . import services


def start(r, st: dict) -> None:
    node, mode, dur = st["node"], st["mode"], st["duration"]
    a = r.base + r.t
    w = {"fid": st["fid"], "cls": st["cls"], "node": node, "mode": mode, "from": r.t, "to": r.t + dur}
    r.faults[st["fid"]] = w
    issued, why = True, ""
    try:
        if node == "AUTH":
            (r.svc.auth.outage if mode == "drop" else r.svc.auth.partition)(r.dep, a, a + dur, mode)
        elif node == "ANCHOR":
            stream = r.stream or services.stream_of(r.hist_path)
            r.stream = stream
            if stream is None:
                issued, why = False, "anchor stream unknown (no decision anchored yet)"
            else:
                r.svc.anchor_ctl.partition(stream, a, a + dur, mode)
        elif node.startswith("EXT:"):
            (r.svc.ext.outage(node[4:], r.dep, a, a + dur) if mode == "drop"
             else r.svc.ext.partition(node[4:], r.dep, a, a + dur, mode))
        elif node == "OBS":
            r.obs_windows.append(w)
            r.obs_apply()
        else:
            issued, why = False, f"unknown node {node!r}"
    except Exception as exc:  # noqa: BLE001 - an injection failure is a harness row (injection_miss), never silent
        issued, why = False, f"{type(exc).__name__}: {exc}"[:200]
    if not issued:
        r.harness_row("injection_miss", fid=st["fid"], node=node, why=why)
    r.event("fault_start", fid=st["fid"], cls=st["cls"], node=node, mode=mode, frm=r.t, to=r.t + dur, issued=issued, why=why)
