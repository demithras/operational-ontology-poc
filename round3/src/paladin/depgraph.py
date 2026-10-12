"""The frozen dependency graph (spec/gate5/dependency-graph.json) read as DATA (PROT-H29 s7, C29-7): which dependency nodes an
operation needs to be DECIDED and ACKED. No node, operation, system or domain literal of the graph appears in this module: the
variant only follows the document it is handed (AuthorityBinding.graph)."""
from __future__ import annotations


class DepGraph:
    def __init__(self, graph: dict, domain: str):
        self.g, self.domain = graph, domain
        self._ops = {**graph["operations"].get("*", {}), **graph["operations"].get(domain, {})}

    def known(self, op) -> bool:
        return isinstance(op, str) and op in self._ops

    def mutation(self, op: str) -> tuple:
        """Decision-plane nodes of a governed mutating operation, in the document's order."""
        return tuple(self.g["surfaces"][self._ops[op]["surface"]]["decision"])

    def surface(self, name: str) -> tuple:
        """Decision-plane nodes of a named surface (read / replay / explain)."""
        return tuple(self.g["surfaces"][name].get("decision", ()))

    def outcome(self, op: str) -> tuple:
        return tuple(self._ops[op].get("outcome", ()))

    def nodes(self) -> tuple:
        """Every node this deployment can depend on: the surfaces' decision nodes plus the domain's external-system nodes."""
        out = []
        for s in self.g["surfaces"].values():
            for n in (*s.get("decision", ()), *s.get("outcome", ())):
                if n not in out:
                    out.append(n)
        for nodes in self.g.get("systems", {}).get(self.domain, {}).values():
            for n in nodes:
                if n not in out:
                    out.append(n)
        return tuple(out)
