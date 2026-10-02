"""CONTEXTUAL baseline: a single-operation capability model with explicit effect metadata, under the same attack classes.

This is a ~40-line reference runtime written for this experiment (one generic operation type; every operation gets the
same context; an ``effects`` flag is metadata the runtime checks for authorization). It is NOT a measured industrial
system and not a support condition; it shows what the attack classes do when Function/Action are not different
capability types.
"""
from __future__ import annotations


class Denied(Exception):
    pass


class Ctx:
    """The same context for EVERY operation: reads and writes alike."""

    def __init__(self, world: dict):
        self._w = world

    def read(self, k):
        return self._w.get(k)

    def write(self, k, v):
        self._w[k] = v


class SingleOpRuntime:
    def __init__(self):
        self.world: dict = {"x": 0}
        self.ops: dict = {}

    def register(self, op_id: str, effects: bool, impl, allowed=()):
        self.ops[op_id] = {"effects": effects, "impl": impl, "allowed": set(allowed)}

    def invoke(self, op_id: str, args: dict, principal: str):
        op = self.ops[op_id]  # KeyError = unknown operation
        if op["effects"] and principal not in op["allowed"]:
            raise Denied(f"{principal} may not invoke effectful {op_id}")
        return op["impl"](Ctx(self.world), args)


def attacks() -> list:
    rows = []

    def rt():
        r = SingleOpRuntime()
        r.register("read_x", False, lambda c, a: c.read("x"))
        r.register("set_x", True, lambda c, a: c.write("x", a["v"]), allowed={"planner"})
        return r

    def run(name, cls, fn):
        r = rt()
        before = dict(r.world)
        err = None
        try:
            fn(r)
        except (KeyError, Denied) as e:
            err = type(e).__name__
        rows.append({"attack": name, "attack_class": cls, "world_changed": r.world != before, "refused": err is not None,
                     "exception": err, "violation": r.world != before})
    run("unknown_raw_write_operation", "raw_write", lambda r: r.invoke("raw_write", {"v": 9}, "agent"))
    run("unauthorized_effectful_operation", "unauthorized", lambda r: r.invoke("set_x", {"v": 9}, "agent"))
    run("read_labelled_operation_that_writes", "function_writes",
        lambda r: (r.register("sneaky_read", False, lambda c, a: c.write("x", 99)), r.invoke("sneaky_read", {}, "agent")))
    run("effect_flag_flipped_by_registrant", "gate_bypass",
        lambda r: (r.register("set_x", False, lambda c, a: c.write("x", 7), allowed={"planner"}), r.invoke("set_x", {}, "agent")))
    return rows
