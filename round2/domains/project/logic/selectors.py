"""resource_selector texts outside the Engine grammar (docs/engine_semantics.md section 5), bound per provenance.md.

``ProjectOntology:*``   every resource the request touches belongs to this package (an object type or link type of
                        the Project Ontology); a request that reaches outside the package does not match.
``Threshold:preregistered``  some resource is a Threshold whose governing hypotheses are no longer DRAFT.
They return booleans only; the Engine combines them with the rule's effect.
"""
from __future__ import annotations

from . import facts


def make(ir: dict) -> dict:
    own = {t["id"] for t in ir["object_types"]} | {t["id"] for t in ir["link_types"]}

    def in_package(sctx) -> bool:
        return bool(sctx.resources) and all(r.actual in own for r in sctx.resources)

    def preregistered_threshold(sctx) -> bool:
        hy = facts.hypotheses(sctx.view)
        return any(r.actual == "Threshold" and r.key is not None and any(
            hy[h].get("phase") != "DRAFT" for h in facts.hypotheses_of_threshold(sctx.view, r.key) if h in hy)
            for r in sctx.resources)

    return {"ProjectOntology:*": in_package, "Threshold:preregistered": preregistered_threshold}
