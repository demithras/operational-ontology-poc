"""Renderer core: address allocation, references, type phrases, properties, parameters, cardinalities."""
from __future__ import annotations

from eoo_ir.kinds import RESOURCE_ARRAYS
from eoo_ir.validate import Index

from .vocab import KIND_HEAD, PRIMITIVE_PHRASES, address

ENDPOINT = ("object_types", "interfaces")
EFFECT_KINDS = {"create": ("object_types",), "update": ("object_types",), "delete": ("object_types",),
                "link": ("link_types",), "unlink": ("link_types",), "git_change": ("object_types", "link_types")}
EFFECT_VERB = {"create": "pali", "update": "ante", "delete": "weka", "link": "linja", "unlink": "weka linja",
               "git_change": "sitelen"}
PROP_OWNERS = (("object_types", "properties"), ("link_types", "properties"),
               ("interfaces", "required_properties"), ("observation_types", "properties"))
DETERMINISM = {"deterministic": "pana sama", "nondeterministic": "pana ante", "external-model": "pana tan sona weka"}
DECISION = {"allow": "ken e pali", "deny": "ken ala e pali", "require_approval": "wile e pona tan jan",
            "classify": "kulupu e ijo"}


class _R:
    def __init__(self, pkg: dict):
        self.pkg = pkg
        self.ix = Index({**pkg, "imports": pkg.get("imports", [])})
        self.n: dict[str, int] = {}
        self.body: list[tuple[str, list]] = []
        self.ext_lines: list[tuple[str, list]] = []
        self.ext: dict[tuple[str, str], str] = {}
        self.res = {(k, r["id"]): address(KIND_HEAD[k], i) for k in RESOURCE_ARRAYS for i, r in enumerate(pkg[k])}
        self.imp: dict[str, str] = {}
        for i, s in enumerate(pkg.get("imports", [])):
            self.imp.setdefault(s, address("kulupu", i))
        self.n["kulupu"] = len(pkg.get("imports", []))
        self.prop: dict[tuple[str, str, str], str] = {}
        for kind, key in PROP_OWNERS:
            for r in pkg[kind]:
                for p in r.get(key, []):
                    self.prop[(kind, r["id"], p["name"])] = self.new("sona")

    def new(self, head: str) -> str:
        i = self.n.get(head, 0)
        self.n[head] = i + 1
        return address(head, i)

    def emit(self, text: str, atoms: list | None = None) -> None:
        self.body.append((text, list(atoms or [])))

    # ---------------------------------------------------------- references
    def ref(self, ref: str, kinds, prefix: str = "", allow_prop: bool = False) -> str:
        m = self.ix.resolve(ref, kinds, prefix, allow_prop)
        assert len(m) == 1, (ref, m)  # validate() passed, so every reference resolves uniquely
        m0 = m[0]
        if m0[0] == "import":
            imp = m0[1]
            key = (imp, ref[len(imp) + 1:])
            if key not in self.ext:
                self.ext[key] = self.new("weka")
                self.ext_lines.append((f"{self.ext[key]} li tan {self.imp[imp]}", [key[1]]))
            return self.ext[key]
        if len(m0) == 3:
            return self.prop[m0]
        return self.res[m0]

    def type_phrase(self, te) -> tuple[str, list]:
        """Phrase for a type plus the type-node lines it needs (pre-order)."""
        if isinstance(te, str):
            return " ".join(PRIMITIVE_PHRASES[te]), []
        if "ref" in te:
            return self.ref(te["ref"], ENDPOINT), []
        node = self.new("nasin")
        inner, sub = self.type_phrase(te["list"] if "list" in te else te["optional"])
        line = f"{node} li linja e {inner}" if "list" in te else f"{node} li {inner} anu ala"
        return node, [(line, [])] + sub

    def typed(self, subj: str, te) -> None:
        phrase, sub = self.type_phrase(te)
        self.emit(f"{subj} li {phrase}")
        self.body.extend(sub)

    # ---------------------------------------------------------- pieces
    def props(self, kind: str, owner: dict, key: str) -> None:
        a = self.res[(kind, owner["id"])]
        if kind == "link_types" and key in owner and owner[key] == []:
            self.emit(f"{a} li sona e ala")
        for p in owner.get(key, []):
            s = self.prop[(kind, owner["id"], p["name"])]
            self.emit(f"{a} li sona e {s}", [p["name"]])
            self.typed(s, p["type"])
            self.emit(f"{s} li wile" + ("" if p["required"] else " ala"))
            if "immutable" in p:
                self.emit(f"{s} li awen" + ("" if p["immutable"] else " ala"))
            if "description" in p:
                self.emit(f"{s} li sitelen e toki ni", [p["description"]])
            if "constraints" in p and p["constraints"] == []:
                self.emit(f"ala li lawa e {s}")
            for c in p.get("constraints", []):
                self.emit(f"nasin ni li lawa e {s}", [c])

    def params(self, a: str, params: list) -> None:
        for p in params:
            s = self.new("kute")
            self.emit(f"{a} li kute e {s}", [p["name"]])
            self.typed(s, p["type"])
            if "required" in p:
                self.emit(f"{s} li wile" + ("" if p["required"] else " ala"))

    def card(self, a: str, side: str, c: dict) -> None:
        self.emit(f"{side} la {a} li lon e kulupu ni", [str(c["min"])])
        if c["max"] == "*":
            self.emit(f"{side} la {a} li ken e kulupu ale")
        else:
            self.emit(f"{side} la {a} li ken e kulupu ni", [str(c["max"])])

