"""Real-domain round trips: both registered domains, both surfaces, committed artifacts AND fresh renders."""
from __future__ import annotations

import eoo_dsl
import eoo_openpona
import eoo_openpona.compiler as op_compiler
from eoo_ir import equivalent, validate
from eoo_openpona import load_record

from .roundtrip import attempt, public
from .surfaces import DSL, OPENPONA
from .util import ROOT, canon, load_json, resource_counts

DOMAINS = ("manufacturing", "project")


def _judge(ir: dict, compile_fn) -> dict:
    try:
        out = compile_fn()
    except Exception as e:  # noqa: BLE001 - the failure itself is the result
        return {"compiled": False, "equivalent": False, "error": f"{type(e).__name__}: {str(e)[:300]}", "diffs": [],
                "exact": False, "valid_ir": False, "resource_counts_out": None}
    eq = equivalent(ir, out)
    return {"compiled": True, "equivalent": eq.ok, "diffs": eq.diffs[:10], "exact": canon(out) == canon(ir),
            "valid_ir": validate(out) == [], "resource_counts_out": resource_counts(out)}


def run() -> dict:
    out = {}
    for d in DOMAINS:
        ir = load_json(f"domains/{d}/ir.json")
        op_text = (ROOT / f"domains/{d}/openpona.op").read_text()
        op_rec_text = (ROOT / f"domains/{d}/openpona.record.json").read_text()
        dsl_text = (ROOT / f"domains/{d}/dsl.yaml").read_text()
        fresh_text, fresh_rec = eoo_openpona.render(ir)
        committed = _judge(ir, lambda: op_compiler.compile(op_text, load_record(op_rec_text)))
        fresh = _judge(ir, lambda: OPENPONA.compile((fresh_text, fresh_rec)))
        dsl_committed = _judge(ir, lambda: DSL.compile(dsl_text))
        dsl_fresh = _judge(ir, lambda: DSL.compile(eoo_dsl.render(ir)))
        rc = resource_counts(ir)
        out[d] = {
            "resources_ir": rc, "resources_total": sum(rc.values()),
            "openpona": {"committed": committed, "fresh_render": fresh,
                         "committed_equals_fresh_render": op_text == fresh_text and load_record(op_rec_text) == fresh_rec,
                         "equivalent": committed["equivalent"] and fresh["equivalent"],
                         "encoded_completely": committed["compiled"] and fresh["compiled"] and
                         committed["resource_counts_out"] == rc and fresh["resource_counts_out"] == rc,
                         "lines": len(op_text.splitlines()), "record_atoms": len(load_record(op_rec_text))},
            "dsl": {"committed": dsl_committed, "fresh_render": dsl_fresh, "committed_equals_fresh_render": dsl_text == eoo_dsl.render(ir),
                    "equivalent": dsl_committed["equivalent"] and dsl_fresh["equivalent"],
                    "encoded_completely": dsl_committed["compiled"] and dsl_fresh["compiled"] and
                    dsl_committed["resource_counts_out"] == rc and dsl_fresh["resource_counts_out"] == rc},
        }
    return out
