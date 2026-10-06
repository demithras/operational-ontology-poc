"""IR -> (OpenPona text, record). Deterministic; refuses invalid IR; never lossy."""
from __future__ import annotations

import json

from eoo_ir.kinds import AUTH_PREFIX, POLICY_PREFIX
from eoo_ir.validate import READS_KINDS, validate

from .errors import InvalidIR
from .gaps import check_representable
from .render_base import DECISION, DETERMINISM, EFFECT_KINDS, EFFECT_VERB, ENDPOINT, _R as _Base
from .vocab import address


class _R(_Base):
    # ---------------------------------------------------------- resources
    def resources(self) -> None:
        p = self.pkg
        for o in p["object_types"]:
            a = self.res[("object_types", o["id"])]
            self.emit(f"{a} li lon", [o["id"]])
            if "description" in o:
                self.emit(f"{a} li sitelen e toki ni", [o["description"]])
            for i in o["implements"]:
                self.emit(f"{a} li sama e {self.ref(i, ('interfaces',))}")
            self.props("object_types", o, "properties")
            self.emit(f"{a} li ni tan {self.prop[('object_types', o['id'], o['primary_key'])]}")
        for lk in p["link_types"]:
            a = self.res[("link_types", lk["id"])]
            self.emit(f"{a} li lon", [lk["id"]])
            self.emit(f"{a} li linja e {self.ref(lk['to'], ENDPOINT)} tan {self.ref(lk['from'], ENDPOINT)}")
            self.card(a, "tan ijo", lk["from_cardinality"])
            self.card(a, "tawa ijo", lk["to_cardinality"])
            if "directed" in lk:
                self.emit(f"{a} li tawa" + ("" if lk["directed"] else " ala"))
            self.props("link_types", lk, "properties")
        for it in p["interfaces"]:
            a = self.res[("interfaces", it["id"])]
            self.emit(f"{a} li lon", [it["id"]])
            self.props("interfaces", it, "required_properties")
            for r in it["required_links"]:
                self.emit(f"{a} li wile e {self.ref(r, ('link_types',))}")
            for c in it["capabilities"]:
                self.emit(f"{a} li ken e ken ni", [c])
        for f in p["functions"]:
            a = self.res[("functions", f["id"])]
            self.emit(f"{a} li lon", [f["id"]])
            self.emit(f"{a} li ante ala e ijo")
            self.params(a, f["inputs"])
            phrase, sub = self.type_phrase(f["output"])
            self.emit(f"{a} li pana e {phrase}")
            self.body.extend(sub)
            for r in f["reads"]:
                self.emit(f"{a} li lukin e {self.ref(r, READS_KINDS, allow_prop=True)}")
            self.emit(f"{a} li tan ilo ni", [f["implementation_ref"]])
            if "determinism" in f:
                self.emit(f"{a} li {DETERMINISM[f['determinism']]}")
        for ac in p["actions"]:
            self.action(ac)
        for po in p["policies"]:
            a = self.res[("policies", po["id"])]
            self.emit(f"{a} li lon", [po["id"]])
            self.emit(f"{a} li {DECISION[po['decision']]}")
            self.emit(f"{a} li tan nasin ni", [po["expression_ref"]])
            self.emit(f"tenpo ni la {a} li lon", [po["version"]])
        for au in p["authority_rules"]:
            a = self.res[("authority_rules", au["id"])]
            self.emit(f"{a} li lon", [au["id"]])
            self.emit(f"{a} li ma e jan ni", [au["principal_selector"]])
            self.emit(f"{a} li open e ken ni", [au["capability"]])
            self.emit(f"{a} li ma e ijo ni", [au["resource_selector"]])
            self.emit(f"{a} li ken" + ("" if au["effect"] == "allow" else " ala"))
            if "delegation_allowed" in au:
                self.emit(f"{a} li pana" + ("" if au["delegation_allowed"] else " ala") + " e ken")
        for ob in p["observation_types"]:
            a = self.res[("observation_types", ob["id"])]
            self.emit(f"{a} li lon", [ob["id"]])
            self.emit(f"{a} li lukin e {self.ref(ob['subject_type'], ('object_types',))}")
            self.props("observation_types", ob, "properties")
            self.emit(f"{a} li kama tan kute ni", [ob["source_binding"]])
            self.emit(f"{a} li tan lukin")
        for c in p["constraints"]:
            a = self.res[("constraints", c["id"])]
            self.emit(f"{a} li lon", [c["id"]])
            self.emit(f"ma ni la {a} li lon", [c["scope"]])
            self.emit(f"{a} li tan nasin ni", [c["expression_ref"]])
            self.emit(f"{a} li ken" + (" ala" if c["severity"] == "hard" else "") + " e weka")

    def action(self, ac: dict) -> None:
        a = self.res[("actions", ac["id"])]
        self.emit(f"{a} li lon", [ac["id"]])
        self.params(a, ac["inputs"])
        for r in ac["authority_refs"]:
            self.emit(f"{a} li ken tan {self.ref(r, ('authority_rules',), AUTH_PREFIX)}")
        for r in ac["policy_refs"]:
            self.emit(f"{a} li lawa tan {self.ref(r, ('policies',), POLICY_PREFIX)}")
        for c in ac["preconditions"]:
            self.emit(f"lon ni la {a} li ken", [c])
        for e in ac["effects"]:
            s = self.new("ante")
            self.emit(f"{a} li pali e {s}")
            op = e["operation"]
            local = None
            if op == "external_call":
                self.emit(f"{s} li toki e ilo ni", [e["target"]])
            else:
                m = self.ix.resolve(e["target"], EFFECT_KINDS[op])
                local = m[0] if m[0][0] != "import" else None
                self.emit(f"{s} li {EFFECT_VERB[op]} e {self.ref(e['target'], EFFECT_KINDS[op])}")
            if "fields" in e and e["fields"] == []:
                self.emit(f"{s} li ma e ala")
            for fld in e.get("fields", []):
                if local is None:
                    self.emit(f"{s} li ma e sona ni", [fld])
                else:
                    self.emit(f"{s} li ma e {self.prop[(local[0], local[1], fld)]}")
        self.emit(f"{a} li wile" + ("" if ac["idempotency"] == "required" else " ala") + " e sike sama")
        self.emit(f"{a} li kama e lon ni", [ac["outcome_predicate"]])
        if "compensation_action" in ac:
            ca = ac["compensation_action"]
            self.emit(f"{a} li nasin weka e " + ("ala" if ca is None else self.ref(ca, ("actions",))))
        self.emit(f"tenpo ni la {a} li lon", [ac["version"]])

    # ---------------------------------------------------------- metadata
    def meta_value(self, node: str, v, out: list) -> None:
        if isinstance(v, bool):
            out.append((f"{node} li sama e " + ("lon" if v else "lon ala"), []))
        elif v is None:
            out.append((f"{node} li sama e ala", []))
        elif isinstance(v, int):
            out.append((f"{node} li kulupu ijo li sama e ni", [str(v)]))
        elif isinstance(v, float):
            out.append((f"{node} li kulupu pilin li sama e ni", [json.dumps(v)]))
        elif isinstance(v, str):
            out.append((f"{node} li sitelen toki li sama e ni", [v]))
        elif isinstance(v, list):
            if not v:
                out.append((f"{node} li linja e ala", []))
            for item in v:
                c = self.new("sitelen")
                out.append((f"{node} li linja e {c}", []))
                self.meta_value(c, item, out)
        elif isinstance(v, dict):
            self.meta_object(node, v, out)
        else:  # pragma: no cover - not JSON
            raise InvalidIR("metadata", f"not a JSON value: {type(v).__name__}")

    def meta_object(self, node: str, d: dict, out: list) -> None:
        if not d:
            out.append((f"{node} li sona e ala", []))
        for k, v in d.items():
            c = self.new("sitelen")
            out.append((f"{node} li sona e {c}", [k]))
            self.meta_value(c, v, out)



def render(ir: dict) -> tuple[str, dict]:
    """(text, record): one OpenPona statement per line; record maps 'L<line>.a<slot>' to atom strings."""
    errs = validate(ir)
    if errs:
        raise InvalidIR("invalid_ir", "; ".join(str(e) for e in errs[:5]))
    check_representable(ir)
    r = _R(ir)
    head: list[tuple[str, list]] = [("kulupu li lon", [ir["package_id"]]),
                                    ("tenpo ni la kulupu li lon", [ir["version"]])]
    if "domain_id" in ir:
        head.append(("ma ni la kulupu li lon", [ir["domain_id"]]))
    if "imports" in ir and ir["imports"] == []:
        head.append(("kulupu li kute e ala", []))
    for i, s in enumerate(ir.get("imports", [])):
        head.append((f"kulupu li kute e {address('kulupu', i)}", [s]))
    meta: list[tuple[str, list]] = []
    if "metadata" in ir:
        md = ir["metadata"]
        if not md:
            meta.append(("kulupu li sona e ala", []))
        for k, v in md.items():
            c = r.new("sitelen")
            meta.append((f"kulupu li sona e {c}", [k]))
            r.meta_value(c, v, meta)
    r.resources()
    lines = head + r.ext_lines + meta + r.body
    record: dict[str, str] = {}
    for n, (_, atoms) in enumerate(lines, 1):
        for j, a in enumerate(atoms, 1):
            record[f"L{n}.a{j}"] = a
    return "".join(t + "\n" for t, _ in lines), record
