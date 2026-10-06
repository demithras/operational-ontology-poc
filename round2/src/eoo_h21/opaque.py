"""Harness-side opaque selector predicates for the Toolchain's surfaces (domain-supplied logic, injected; never part of
eoo_toolchain). Semantics of the two selector texts both domains use, over the case world (not engine state)."""
from __future__ import annotations


def make(ir: dict) -> dict:
    own = {o["id"] for o in ir["object_types"]} | {x["id"] for x in ir["link_types"]}

    def faulty(ctx) -> bool:
        if ctx.world is not None and ctx.world.flags.get("fault"):
            raise RuntimeError("selector fault")
        return False

    def in_package(ctx) -> bool:
        faulty(ctx)
        return bool(ctx.resources) and all(r.actual in own for r in ctx.resources)

    def preregistered(ctx) -> bool:
        faulty(ctx)
        pre = set(ctx.world.flags.get("preregistered", ())) if ctx.world is not None else set()
        return any(r.actual == "Threshold" and r.key is not None and r.key in pre for r in ctx.resources)

    return {"ProjectOntology:*": in_package, "Threshold:preregistered": preregistered}
