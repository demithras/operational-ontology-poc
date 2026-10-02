"""Workloads driven under the tracer: both domain end-to-end suites, the H17 state machine sample, a generic sweep."""
from __future__ import annotations

import importlib.util
import random
import sys

import pytest

from eoo_engine import Engine
from eoo_exp.util import ROOT

SUITE_ARGS = ["tests/domains", "tests/h18/test_git_store.py"]  # both domains end to end; Project over the Git-backed adapter


class _Counts:
    def __init__(self):
        self.c = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}
        self.failed_ids: list = []

    def pytest_runtest_logreport(self, report):
        if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
            k = "error" if report.when == "setup" and report.outcome == "failed" else report.outcome
            self.c[k] = self.c.get(k, 0) + 1
            if report.outcome == "failed":
                self.failed_ids.append(report.nodeid)


def run_pytest(args: list[str] | None = None) -> dict:
    """Run pytest IN PROCESS (so the tracer's patches are live). The ROOT must be cwd-independent."""
    import os
    args = args or SUITE_ARGS
    counts, old = _Counts(), os.getcwd()
    os.chdir(ROOT)
    try:
        rc = pytest.main(["-q", "-p", "no:cacheprovider", "-x", "--no-header", *args], plugins=[counts])
    finally:
        os.chdir(old)
    return {"args": args, "exit_code": int(rc), **counts.c, "failed_ids": counts.failed_ids[:10]}


def machine_sample(seed: int, per_domain: int) -> dict:
    from eoo_h17.runlib import new_sink, run_machine
    out = {}
    for k, d in enumerate(("manufacturing", "project")):
        sink = run_machine(d, seed * 100 + k, per_domain, step_count=14, sink=new_sink())
        out[d] = {"examples": len(sink["records"]), "failures": len(sink["failures"])}
    return out


def _genbind():
    p = ROOT / "tests/engine/genbind.py"
    spec = importlib.util.spec_from_file_location("h20_genbind", p)
    m = importlib.util.module_from_spec(spec)
    sys.modules["h20_genbind"] = m
    spec.loader.exec_module(m)
    return m


def generic_sweep(seeds: range) -> dict:
    """Every registered Action of both domain IRs proposed through the Engine with GENERATED bindings (no domain logic)."""
    from domains._pack import load_ir
    g = _genbind()
    res = {}
    for dom in ("manufacturing", "project"):
        n = states = 0
        seen = set()
        for sd in seeds:
            for mode in ("permissive", "random"):
                pkg = g.permissive_variant(load_ir(dom))
                model, b, reg, _ad = g.bind_all(pkg, mode, random.Random(sd))
                clock = iter(range(10 ** 9))
                eng = Engine(pkg, b, reg, clock=lambda: f"c{next(clock)}")
                g.seed(eng, model)
                for p in g.principals(model, eng):
                    eng.register_principal(p)
                for aid, spec in sorted(model.all("actions").items()):
                    inputs = g.inputs_for(spec, eng.read_view(), model)
                    rec = eng.propose(aid, inputs if inputs is not None else {}, "tester", idempotency_key=f"k-{aid}")
                    if rec["state"] == "PENDING_APPROVAL":
                        try:
                            rec = eng.approve(rec["exec"], "second")
                        except Exception:  # noqa: BLE001 - a refused approval is a lifecycle fact, recorded by the tracer
                            pass
                    n += 1
                    seen.add(aid)
                    states += rec["state"] in ("RECONCILED_SUCCESS", "RECONCILED_FAILED", "OUTCOME_UNKNOWN", "DENIED", "PENDING_APPROVAL")
        res[dom] = {"proposals": n, "actions_proposed": sorted(seen), "all_in_known_states": states == n}
    return res


def read_sweep() -> dict:
    """Every registered object type / interface / link type / Function of both domains dispatched once on the real seeded pack
    (Function arguments are generated from the declared parameter types). Counts completed vs refused calls."""
    from eoo_h17.drivers import new_driver
    g = _genbind()
    res = {}
    for dom in ("manufacturing", "project"):
        e = new_driver(dom, "std").engine
        m, ok, refused = e.model, 0, 0

        def attempt(fn):
            nonlocal ok, refused
            try:
                fn()
                ok += 1
            except Exception:  # noqa: BLE001 - dispatch happened (the tracer saw it); a refusal is a result, counted
                refused += 1
        for t in sorted(m.all("object_types")):
            attempt(lambda t=t: e.dispatch("object_types", "list", t))
            for r in e.dispatch("object_types", "list", t)[:1]:
                attempt(lambda t=t, r=r: e.dispatch("object_types", "get", t, key=r["key"]))
        for i in sorted(m.all("interfaces")):
            attempt(lambda i=i: e.dispatch("interfaces", "query", i))
        for lt, spec in sorted(m.all("link_types").items()):
            kind = "interfaces" if spec.src in m.all("interfaces") else "object_types"
            for r in e.dispatch(kind, "query" if kind == "interfaces" else "list", spec.src)[:60]:
                attempt(lambda lt=lt, spec=spec, r=r: e.dispatch("link_types", "follow", lt, t=spec.src, key=r["key"]))
                if e.dispatch("link_types", "follow", lt, t=spec.src, key=r["key"]):
                    break  # a non-empty traversal: this link type has been read for real
        for fid, f in sorted(m.all("functions").items()):
            attempt(lambda f=f, fid=fid: e.dispatch("functions", "call", fid, args={p.pname: g.value(p.type, e.read_view(), m, concrete=True)
                                                                                    for p in f.inputs if p.required}))
        res[dom] = {"completed": ok, "refused": refused}
    return res
