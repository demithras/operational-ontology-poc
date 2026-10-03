"""Dispatch / lifecycle / adapter-boundary tracing of the UNCHANGED Engine (monkeypatch wrappers; nothing is edited on disk).

Records, per package id: every (kind, op, resource id) that went through ``Engine.dispatch`` (via the handler ``ops``
table), every action execution's state history, gate outcomes and the keys of its provenance record, and every call the
Engine's governance code receives while an adapter method is running (``in_adapter`` taint).
"""
from __future__ import annotations

import itertools
import sys
from collections import Counter, defaultdict
from contextlib import ExitStack, contextmanager
from unittest import mock

from eoo_engine import authority, effects, engine as engine_mod, gates, journal, pipeline, registry

GUARDED_MODULE_FNS = (("authority", authority, "evaluate"), ("gates", gates, "run_logic_gate"),
                      ("gates", gates, "evaluate_policies"), ("gates", gates, "check_inputs"),
                      ("pipeline", pipeline, "propose"), ("pipeline", pipeline, "run_gates"),
                      ("pipeline", pipeline, "decide_approval"), ("pipeline", pipeline, "execute"))
GUARDED_ENGINE = ("record", "_write", "new_execution", "note_retry", "note_attempt", "register_principal", "seed")


class Tracer:
    def __init__(self):
        self.dispatch = Counter()  # (pkg, kind, op) -> calls
        self.rids = defaultdict(set)  # (pkg, kind) -> resource ids dispatched
        self.handler_ids = defaultdict(set)  # kind -> {id(handler)}
        self.handler_classes = defaultdict(set)
        self.execs: dict = {}  # (engine serial, exec id) -> row
        self.authority_rules_seen = defaultdict(set)  # pkg -> rule ids named by an authority gate's allow/deny
        self.adapter_calls = Counter()  # (adapter class, method)
        self.adapter_violations: list = []
        self.in_adapter = 0
        self.in_dispatch = 0
        self.dispatch_files: Counter = Counter()
        self._serial = itertools.count(1)
        self.prov_fields = defaultdict(set)  # pkg -> {tuple(sorted keys)}
        self.engines = Counter()
        self.prov_writes = Counter()  # adapter class -> provenance-bearing external writes observed (new commit per envelope)
        self.prov_mismatches: list = []  # written text != effect['envelope_text'], byte for byte
        self._written_ids: set = set()

    # ---- wrappers ---------------------------------------------------------------------------
    def _pkg(self, eng) -> str:
        return eng.model.package_id

    def wrap_op(self, kind, op, fn):
        t = self

        def w(eng, spec, **kw):
            pkg = t._pkg(eng)
            t.dispatch[(pkg, kind, op)] += 1
            if spec is not None:
                t.rids[(pkg, kind)].add(spec.rid)
            elif "refs" in kw:
                pass
            t.in_dispatch += 1
            try:
                return fn(eng, spec, **kw)
            finally:
                t.in_dispatch -= 1
        return w

    def _row(self, eng, rec):
        ser = getattr(eng, "_h20_serial", None)
        if ser is None:
            ser = eng._h20_serial = next(self._serial)
            self.engines[self._pkg(eng)] += 1
        key = (ser, rec["exec"])
        row = self.execs.get(key)
        if row is None:
            row = self.execs[key] = {"pkg": self._pkg(eng), "action": rec["action"]}
        return row

    def wrap_record(self, orig):
        t = self

        def record(eng, rec, state, note=None, commit=None, fault=None):
            try:
                return orig(eng, rec, state, note=note, commit=commit, fault=fault)
            finally:  # also when a SimulatedCrash is raised: the journal record was written first
                row = t._row(eng, rec)
                row["history"] = list(rec["history"])
                row["gates"] = [(g["gate"], g["passed"]) for g in rec["gates"]]
                for g in rec["gates"]:
                    if g["gate"] == "authority" and isinstance(g["detail"], dict):
                        t.authority_rules_seen[row["pkg"]].update(g["detail"].get("allow", []) + g["detail"].get("deny", []))
                ents = eng.provenance.entries()
                if ents:
                    keys = tuple(sorted(ents[-1]))
                    t.prov_fields[row["pkg"]].add(keys)
                    row["prov_keys"] = keys
        return record

    def guard(self, label, fn):
        t = self

        def g(*a, **k):
            if t.in_adapter:
                t.adapter_violations.append({"called": label, "adapter": t.current_adapter})
            return fn(*a, **k)
        return g

    def wrap_adapter(self, adapter):
        """Instance-level wrap of apply/observations: the call runs with the ``in_adapter`` taint set."""
        if getattr(adapter, "_h20_wrapped", False):
            return
        t, cls = self, type(adapter).__name__
        for m in ("apply", "observations"):
            orig = getattr(adapter, m)

            def w(*a, _orig=orig, _m=m, **k):
                t.adapter_calls[(cls, _m)] += 1
                prev = t.current_adapter
                t.in_adapter += 1
                t.current_adapter = f"{cls}.{_m}"
                try:
                    out = _orig(*a, **k)
                finally:
                    t.in_adapter -= 1
                    t.current_adapter = prev
                if _m == "apply":
                    t.check_provenance_write(adapter, a[0] if a else k.get("effect"), out)
                return out
            setattr(adapter, m, w)
        adapter._h20_wrapped = True

    current_adapter = None

    def check_provenance_write(self, adapter, effect, response) -> None:
        """Behavioural twin of the static provenance_composition rule: the text the adapter actually wrote into the external system
        (Git commit message) must equal effect['envelope_text'] byte for byte. Only a call that created a NEW external artifact counts
        (a repeated answer for an already-written commit, or the other effects of a batch commit, wrote nothing)."""
        from .provenance_writes import written_text
        env = effect.get("envelope_text") if isinstance(effect, dict) or hasattr(effect, "get") else None
        if env is None or not isinstance(response, dict) or "commit" not in response:
            return
        key = (id(adapter), response["commit"])
        if key in self._written_ids:
            return
        text = written_text(adapter, response["commit"])
        if text is None:  # not a provenance-bearing artifact store we can read (e.g. the WMS fake): nothing to compare
            return
        self._written_ids.add(key)
        cls = type(adapter).__name__
        self.prov_writes[cls] += 1
        if text != env:
            self.prov_mismatches.append({"adapter": cls, "effect_id": effect.get("effect_id"), "commit": response["commit"],
                                         "written": text[:300], "envelope_text": env[:300]})

    def provenance_numbers(self) -> dict:
        return {"adapter_provenance_writes": sum(self.prov_writes.values()), "by_adapter": dict(self.prov_writes),
                "adapter_provenance_verbatim_mismatches": len(self.prov_mismatches), "first_mismatches": self.prov_mismatches[:5]}

    # ---- install ----------------------------------------------------------------------------
    @contextmanager
    def installed(self):
        t = self
        with ExitStack() as es:
            for kind, h in registry.DISPATCH_TABLE.items():
                self.handler_ids[kind].add(id(h))
                self.handler_classes[kind].add(type(h).__qualname__)
                es.enter_context(mock.patch.dict(h.ops, {op: self.wrap_op(kind, op, fn) for op, fn in h.ops.items()}))
            orig_record = engine_mod.Engine.record
            es.enter_context(mock.patch.object(engine_mod.Engine, "record", self.wrap_record(self.guard("Engine.record", orig_record))))
            for name in GUARDED_ENGINE:
                if name != "record":
                    es.enter_context(mock.patch.object(engine_mod.Engine, name, self.guard("Engine." + name, getattr(engine_mod.Engine, name))))
            for label, mod, name in GUARDED_MODULE_FNS:
                es.enter_context(mock.patch.object(mod, name, self.guard(f"{label}.{name}", getattr(mod, name))))
            es.enter_context(mock.patch.object(journal.Journal, "append", self.guard("Journal.append", journal.Journal.append)))
            es.enter_context(mock.patch.object(journal.AppendOnlyLog, "append", self.guard("AppendOnlyLog.append", journal.AppendOnlyLog.append)))
            orig_reg = effects.AdapterRegistry.register

            def register(reg, operation, target, adapter):
                orig_reg(reg, operation, target, adapter)
                t.wrap_adapter(adapter)
            es.enter_context(mock.patch.object(effects.AdapterRegistry, "register", register))
            yield self


@contextmanager
def profiling_dispatch(tracer: Tracer):
    """Record the file of every Python call made while the Engine is inside ``dispatch`` (files that really participate)."""
    def prof(frame, event, arg):
        if event == "call" and tracer.in_dispatch:
            tracer.dispatch_files[frame.f_code.co_filename] += 1
    old = sys.getprofile()
    sys.setprofile(prof)
    try:
        yield
    finally:
        sys.setprofile(old)
