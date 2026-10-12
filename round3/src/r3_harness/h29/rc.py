"""Recovery checkpoints (PROTOCOL-P1g P1g-7): RC1 after every resume (two hosts from byte copies under the RESTRICTED dependency state,
byte-compared recovery_view()), RC2 at the end of each recovery event (heal, dispatch, reconcile, AUTH probe, recovery_view, redelivery
of every committed request_id). Only raw observations are recorded here."""
from __future__ import annotations

import shutil
from pathlib import Path

from r3_oracle import continuity as C
from r3_shared.world import WorldReader

from . import faults, services
from .driver import _res


def do_tamper(r, st) -> None:
    if r.host is not None and r.host.alive:
        if not (r.kills and r.kills[-1].get("resume") is None):
            r.harness_row("tamper_host_alive")      # TamperView is applied while the host is DEAD (F8): kill it first, hard
            r._died()
        r.host.kill()                                # a host already recorded as killed may still be exiting: reap it
    rec = services.tamper(st["what"], r.hist_path, r.world_path, r.layout)
    r.event("tamper", **rec)


def _view(px, r):
    try:
        return px.recovery_view(), None
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"[:200]


def resume(r) -> None:
    if r.host is not None and r.host.alive:
        recorded = bool(r.kills) and r.kills[-1].get("resume") is None
        if not recorded:
            r.harness_row("injection_miss", why="armed crash point never fired", detail="resume with a live host: SIGKILL")
            r._died()
        r.host.kill()
    if not r.kills or r.kills[-1].get("resume") is not None:
        r.kills.append({"kill": r.t, "resume": None})
    r.kills[-1]["resume"] = r.t
    T, dep_b = r.t, r.dep + "~rc1b"
    copy_dir = r.work / "rc1copy"
    names = services.copy_store(r.work, copy_dir)
    for dep in (r.dep, dep_b):                               # RESTRICTED dependency state at tick T (server-side, both deployment ids)
        r.svc.auth.outage(dep, r.base + T, r.base + T + 1, "drop")
        for s in r.systems["systems"]:
            r.svc.ext.outage(s, dep, r.base + T, r.base + T + 1)
    services.obs_set(r.work / "obs-a", r.svc.ext_dir, False)
    stream = r.stream or services.stream_of(r.hist_path)
    head0, aseq0 = _head(r, stream), _auth_seq(r)
    px_a = r.start_host(True)
    px_b = r.start_host(True, dep=dep_b, paths={"world": str(copy_dir / "world.db"), "hist": str(copy_dir / "hist.db")}, obs_tag="b") if names else None
    va, ea = _view(px_a, r) if px_a is not None else (None, "no_host")
    vb, eb = _view(px_b, r) if px_b is not None else (None, "no_host")
    if px_b is not None:
        try:
            px_b.close()
        except Exception:  # noqa: BLE001
            px_b.kill()
    shutil.rmtree(copy_dir, ignore_errors=True)
    head1, aseq1 = _head(r, stream), _auth_seq(r)
    restricted_auth = _auth_refused_between(r, aseq0, aseq1)       # G5-E25: the window ends at the harness's first call other than recovery_view()
    marks = _marks(r)
    r.event("rc1", resume=T, view_a=va, view_b=vb, err_a=ea, err_b=eb, anchor_head_before=head0, anchor_head_after=head1, auth_refused_restricted=restricted_auth,
            marks=marks, files=names, a_started=px_a is not None)
    r.open_recoveries.append({"resume": T})
    r.stream = stream
    r.tick_to(r.t + 1)                     # one tick after RC1 (ORACLE-AND-HARNESS-G5 s2): nothing is sent at the restricted tick


def _auth_seq(r):
    try:
        return max([x["seq"] for x in r.svc.auth.log()["refused"]], default=0)
    except Exception:  # noqa: BLE001
        return None


def _auth_refused_between(r, lo, hi) -> int:
    """Refusals of the resumed deployment recorded by the service after `lo` and up to `hi` (service sequence = transcript order)."""
    if lo is None or hi is None:
        return 0
    try:
        return sum(1 for x in r.svc.auth.log()["refused"] if x["deployment"] == r.dep and lo < x["seq"] <= hi)
    except Exception:  # noqa: BLE001
        return 0


def _head(r, stream):
    if not stream:
        return None
    try:
        h = r.svc.anchor.head(stream)
        return None if h is None else h["seq"]
    except Exception:  # noqa: BLE001 - the anchor may be partitioned
        return -1


def _marks(r) -> list:
    try:
        rd = WorldReader(r.world_path)
        try:
            return [{"seq": x["seq"], "tick": x["tick"] - r.base, "data": x["data"]} for x in rd.log() if x["kind"] == "mark" and x["ref"] == "commit"]
        finally:
            rd.close()
    except Exception:  # noqa: BLE001
        return []


def rc2(r) -> None:
    """End of each recovery event (all open recoveries close here)."""
    end = max([w["to"] for w in r.faults.values()] + [r.t])
    r.tick_to(end)
    r.obs_apply()
    ext_rids = sorted({e["rid"] for e in r.ev if e["k"] == "request" and e.get("rid") and C.outcome_deps(r.graph, r.seq["domain"], e["operation"])})
    res, err = r.call("dispatch_pending")
    r.event("dispatch", res=_res(res) if res is not None else None, err=err, rc2=True)
    last = max([e["t"] for e in r.ev if e["k"] in ("request", "redeliver")] + [r.t])
    r.tick_to(max(r.t, last + r.systems["window"] + 2))
    for rid in ext_rids:
        x, e = r.call("reconcile", rid, r.base + r.t)
        r.event("reconcile", rid=rid, watermark=r.t, res=_res(x) if x is not None else None, err=e,
                fault=None, rc2=True)
    t_probe = r.t
    admin = next((p["id"] for p in r.auth0["principals"] if "admin" in p.get("roles", [])), r.auth0["principals"][0]["id"])
    ref = sorted(f"{o['type']}:{o['key']}" for o in r.ops["seed"]["objects"])[0]
    t_, k_ = ref.split(":", 1)
    pr, pe = r.call("read", r.token(admin), "get", {"type": t_, "key": k_})
    view, verr = _view(r.host, r) if r.host is not None and r.host.alive else (None, "no_host")
    marks = _marks(r)
    before = len(marks)
    committed = sorted({m["data"].get("request_id") for m in marks if isinstance(m["data"].get("request_id"), str)})
    r.tick_to(r.t + 1)                      # the redelivery tick is free of every other write: new ledger rows at it belong to the redelivery
    t_re = r.t
    redo = []
    for rid in committed:
        spec = r.reqspec.get(rid)
        if spec is None:
            continue
        e = r.send({**spec, "tag": "rc2_redeliver"}, "redeliver", copy=0)
        e["rc2"] = True
        redo.append(rid)
    after = len(_marks(r))
    r.event("rc2", t_probe=t_probe, probe={"status": pr.status, "body_ok": pr.status == "OK"} if pr is not None else None, probe_err=pe,
            view=view, err=verr, marks_before=before, marks_after=after, redelivered=redo, t_redeliver=t_re, marks=marks)
    r.open_recoveries.clear()
