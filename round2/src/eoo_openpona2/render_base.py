"""Renderer core: references, type phrases, properties, parameters, cardinalities.

Every emitted line is (text, atoms) with atoms in the left-to-right order of the line's `ni` slots."""
from __future__ import annotations

from eoo_ir.validate import Index

from .vocab import KIND_HEAD, PRIMITIVE_PHRASES

ENDPOINT = ("object_types", "interfaces")
EFFECT_KINDS = {"create": ("object_types",), "update": ("object_types",), "delete": ("object_types",),
                "link": ("link_types",), "unlink": ("link_types",), "git_change": ("object_types", "link_types")}
EFFECT_VERB = {"create": "pali", "update": "ante", "delete": "weka", "link": "linja", "unlink": "weka linja",
               "git_change": "sitelen"}
DETERMINISM = {"deterministic": "pana sama", "nondeterministic": "pana ante", "external-model": "pana tan sona weka"}
DECISION = {"allow": "ken e pali", "deny": "ken ala e pali", "require_approval": "wile e pona tan jan",
            "classify": "kulupu e ijo"}


class _R:
    def __init__(self, pkg: dict):
        self.pkg = pkg
        self.ix = Index({**pkg, "imports": pkg.get("imports", [])})
        self.body: list[tuple[str, list]] = []

    def emit(self, text: str, atoms: list | None = None) -> None:
        self.body.append((text, list(atoms or [])))

    # ---------------------------------------------------------- references
    def ref(self, ref: str, kinds, prefix: str = "", allow_prop: bool = False) -> tuple[str, list]:
        m = self.ix.resolve(ref, kinds, prefix, allow_prop)
        assert len(m) == 1, (ref, m)  # validate() passed, so every reference resolves uniquely
        m0 = m[0]
        if m0[0] == "import":
            return "weka ni pi kulupu ni", [ref[len(m0[1]) + 1:], m0[1]]
        if len(m0) == 3:
            return f"sona ni pi {KIND_HEAD[m0[0]]} ni", [m0[2], m0[1]]
        return f"{KIND_HEAD[m0[0]]} ni", [m0[1]]

    def type_phrase(self, te) -> tuple[str, list, list]:
        """(phrase, phrase atoms, follow-up type-node lines in pre-order)."""
        if isinstance(te, str):
            return " ".join(PRIMITIVE_PHRASES[te]), [], []
        if "ref" in te:
            ph, at = self.ref(te["ref"], ENDPOINT)
            return ph, at, []
        inner, at, sub = self.type_phrase(te["list"] if "list" in te else te["optional"])
        line = f"nasin li linja e {inner}" if "list" in te else f"nasin li {inner} anu ala"
        return "nasin", [], [(line, at)] + sub

    def typed(self, prefix: str, atoms: list, te) -> None:
        """Emit '<prefix> li <type>' and the type-node lines that complete it."""
        ph, at, sub = self.type_phrase(te)
        self.emit(f"{prefix} li {ph}", atoms + at)
        self.body.extend(sub)

    # ---------------------------------------------------------- pieces
    def props(self, kind: str, owner: dict, key: str) -> None:
        h, oid = KIND_HEAD[kind], owner["id"]
        if kind == "link_types" and key in owner and owner[key] == []:
            self.emit(f"{h} ni li sona e ala", [oid])
        for p in owner.get(key, []):
            nm = p["name"]
            self.emit(f"{h} ni li sona e sona ni", [oid, nm])
            ctx = f"{h} ni la sona ni"
            self.typed(ctx, [oid, nm], p["type"])
            self.emit(f"{ctx} li wile" + ("" if p["required"] else " ala"), [oid, nm])
            if "immutable" in p:
                self.emit(f"{ctx} li awen" + ("" if p["immutable"] else " ala"), [oid, nm])
            if "description" in p:
                self.emit(f"{ctx} li sitelen e toki ni", [oid, nm, p["description"]])
            if "constraints" in p and p["constraints"] == []:
                self.emit(f"{h} ni la ala li lawa e sona ni", [oid, nm])
            for c in p.get("constraints", []):
                self.emit(f"{h} ni la nasin ni li lawa e sona ni", [oid, c, nm])

    def params(self, h: str, oid: str, params: list) -> None:
        for p in params:
            nm = p["name"]
            self.emit(f"{h} ni li kute e kute ni", [oid, nm])
            self.typed(f"{h} ni la kute ni", [oid, nm], p["type"])
            if "required" in p:
                self.emit(f"{h} ni la kute ni li wile" + ("" if p["required"] else " ala"), [oid, nm])

    def card(self, lid: str, side: str, c: dict) -> None:
        self.emit(f"{side} la linja ni li lon e kulupu ni", [lid, str(c["min"])])
        if c["max"] == "*":
            self.emit(f"{side} la linja ni li ken e kulupu ale", [lid])
        else:
            self.emit(f"{side} la linja ni li ken e kulupu ni", [lid, str(c["max"])])
