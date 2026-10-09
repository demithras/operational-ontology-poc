"""Typed request models for operations a deployment's ops spec declares but codegen has not seen (the H28 harness injects one
operation for the unobservable GEN-NULL system, G4-E3/E22). Built from the SAME spec fields and with the SAME interface as the
generated models (SCHEMA / RESOURCES / GATED / APPROVAL / from_args / inputs); registered once per name."""
from __future__ import annotations

from .models_gen import OPERATION_MODELS
from .validation import validate_inputs


def _model(op: dict):
    schema = tuple((i["name"], i["type"], bool(i["required"])) for i in op["inputs"])
    attrs = dict(OPERATION=op["name"], DOMAIN="injected", SCHEMA=schema,
                 RESOURCES={i["name"]: i["resource_type"] for i in op["inputs"] if i["type"] == "resource"},
                 GATED=tuple(op["gated_inputs"]), APPROVAL=(op["approval"] or {}).get("approver_operation"))

    def __init__(self, **kw):
        self.__dict__.update(kw)

    attrs["__init__"] = __init__
    attrs["from_args"] = classmethod(lambda cls, args: cls(**validate_inputs(cls.SCHEMA, args)))
    attrs["inputs"] = lambda self: {n: getattr(self, n, None) for n, _, _ in self.SCHEMA if getattr(self, n, None) is not None}
    return type("Injected" + "".join(p.capitalize() for p in op["name"].split("_")) + "Request", (), attrs)


def ensure_models(ops_spec: dict) -> None:
    for op in ops_spec["operations"]:
        if op["name"] not in OPERATION_MODELS:
            OPERATION_MODELS[op["name"]] = _model(op)
