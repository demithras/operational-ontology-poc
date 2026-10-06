"""Dynamic adapter checks: (1) the Engine owns the idempotency decision; (2) known-negative for the in-adapter taint."""
from __future__ import annotations

from eoo_h17.drivers import new_driver
from eoo_h17.scenarios import ALL

PROBES = {"manufacturing": "m_ok_planner", "project": "p_ok_create"}


def idempotency_probe() -> list[dict]:
    """Same key + same intent twice: the Engine returns the stored execution and the adapter is not called again.
    A different key is a new execution (the Engine, not the adapter, tells the two cases apart)."""
    rows = []
    for dom, sid in PROBES.items():
        scn = next(s for s in ALL[dom] if s.id == sid)
        d = new_driver(dom, scn.profiles[0])
        e = d.engine
        r1 = e.propose(scn.action, scn.inputs, scn.principal, idempotency_key="probe-k1")
        calls1, eff1 = d.external_count(), len(e.effect_log)
        r2 = e.propose(scn.action, scn.inputs, scn.principal, idempotency_key="probe-k1")
        calls2, eff2 = d.external_count(), len(e.effect_log)
        rows.append({"domain": dom, "scenario": sid, "state": r1["state"], "same_execution_on_retry": r1["exec"] == r2["exec"],
                     "adapter_calls_after_first": calls1, "adapter_calls_after_retry": calls2,
                     "effects_after_first": eff1, "effects_after_retry": eff2,
                     "engine_decided": r1["exec"] == r2["exec"] and calls1 == calls2 and eff1 == eff2 and calls1 > 0})
    return rows


def taint_known_negative(tracer_cls) -> dict:
    """An adapter that calls an Engine governance function from inside ``apply`` MUST be recorded by the taint."""
    from eoo_engine import journal
    drv_rows = {}
    t = tracer_cls()
    with t.installed():
        d = new_driver("manufacturing", "std")
        orig = d.adapter.apply

        def evil(effect, payload, _o=orig):
            journal.Journal().append({"kind": "attempt"})  # an adapter writing a journal record = provenance writing
            return _o(effect, payload)
        d.adapter.apply = evil  # instance attribute, same wrap point as the real adapters
        d.adapter._h20_wrapped = False  # re-wrap so the taint covers the replaced method
        t.wrap_adapter(d.adapter)
        scn = next(s for s in ALL["manufacturing"] if s.id == "m_ok_planner")
        d.engine.propose(scn.action, scn.inputs, scn.principal, idempotency_key="neg-1")
        drv_rows = {"violations": list(t.adapter_violations)}
    return {"detected": any(v["called"] == "Journal.append" for v in drv_rows["violations"]), **drv_rows}


def ok_mode_probe(adapter_class=None) -> list[dict]:
    """Every scenario the Engine approves, run with the adapter in mode ``ok``: the adapter must carry it out. An adapter that
    refuses an approved effect without a declared fault mode is deciding something the Engine already decided."""
    rows = []
    for dom in ("manufacturing", "project"):
        for scn in (s for s in ALL[dom] if s.kind == "ok"):
            d = new_driver(dom, scn.profiles[0])
            if adapter_class is not None and dom in adapter_class:
                d.adapter.__class__ = adapter_class[dom]
            rec = d.engine.propose(scn.action, scn.inputs, scn.principal, idempotency_key="ok-1")
            rows.append({"domain": dom, "scenario": scn.id, "state": rec["state"],
                         "adapter_errors": [e["error"][:80] for e in rec.get("adapter_errors", [])],
                         "carried_out": rec["state"] == "RECONCILED_SUCCESS" and not rec.get("adapter_errors")})
    return rows
