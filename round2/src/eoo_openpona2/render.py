"""IR -> (OpenPona v2 text, record). Deterministic; refuses invalid IR; never lossy."""
from __future__ import annotations

import json

from eoo_ir.kinds import AUTH_PREFIX, POLICY_PREFIX
from eoo_ir.validate import READS_KINDS, validate

from .errors import InvalidIR
from .gaps import check_representable
from .render_base import DECISION, DETERMINISM, EFFECT_KINDS, EFFECT_VERB, ENDPOINT, _R as _Base


class _R(_Base):
    def resources(self) -> None:
        p = self.pkg
        for o in p["object_types"]:
            i = o["id"]
            self.emit("ijo ni li lon", [i])
            if "description" in o:
                self.emit("ijo ni li sitelen e toki ni", [i, o["description"]])
            for x in o["implements"]:
                ph, at = self.ref(x, ("interfaces",))
                self.emit(f"ijo ni li sama e {ph}", [i] + at)
            self.props("object_types", o, "properties")
            self.emit("ijo ni li ni tan sona ni", [i, o["primary_key"]])
        for lk in p["link_types"]:
            i = lk["id"]
            self.emit("linja ni li lon", [i])
            (tp, ta), (fp, fa) = self.ref(lk["to"], ENDPOINT), self.ref(lk["from"], ENDPOINT)
            self.emit(f"linja ni li linja e {tp} tan {fp}", [i] + ta + fa)
            self.card(i, "tan ijo", lk["from_cardinality"])
            self.card(i, "tawa ijo", lk["to_cardinality"])
            if "directed" in lk:
                self.emit("linja ni li tawa" + ("" if lk["directed"] else " ala"), [i])
            self.props("link_types", lk, "properties")
        for it in p["interfaces"]:
            i = it["id"]
            self.emit("selo ni li lon", [i])
            self.props("interfaces", it, "required_properties")
            for r in it["required_links"]:
                ph, at = self.ref(r, ("link_types",))
                self.emit(f"selo ni li wile e {ph}", [i] + at)
            for c in it["capabilities"]:
                self.emit("selo ni li ken e ken ni", [i, c])
        for f in p["functions"]:
            i = f["id"]
            self.emit("ilo ni li lon", [i])
            self.emit("ilo ni li ante ala e ijo", [i])
            self.params("ilo", i, f["inputs"])
            self._output(i, f["output"])
            for r in f["reads"]:
                ph, at = self.ref(r, READS_KINDS, allow_prop=True)
                self.emit(f"ilo ni li lukin e {ph}", [i] + at)
            self.emit("ilo ni li tan ilo ni", [i, f["implementation_ref"]])
            if "determinism" in f:
                self.emit(f"ilo ni li {DETERMINISM[f['determinism']]}", [i])
        for ac in p["actions"]:
            self.action(ac)
        for po in p["policies"]:
            i = po["id"]
            self.emit("lawa ni li lon", [i])
            self.emit(f"lawa ni li {DECISION[po['decision']]}", [i])
            self.emit("lawa ni li tan nasin ni", [i, po["expression_ref"]])
            self.emit("tenpo ni la lawa ni li lon", [po["version"], i])
        for au in p["authority_rules"]:
            i = au["id"]
            self.emit("ken ni li lon", [i])
            self.emit("ken ni li ma e jan ni", [i, au["principal_selector"]])
            self.emit("ken ni li open e ken ni", [i, au["capability"]])
            self.emit("ken ni li ma e ijo ni", [i, au["resource_selector"]])
            self.emit("ken ni li ken" + ("" if au["effect"] == "allow" else " ala"), [i])
            if "delegation_allowed" in au:
                self.emit("ken ni li pana" + ("" if au["delegation_allowed"] else " ala") + " e ken", [i])
        for ob in p["observation_types"]:
            i = ob["id"]
            self.emit("lukin ni li lon", [i])
            ph, at = self.ref(ob["subject_type"], ("object_types",))
            self.emit(f"lukin ni li lukin e {ph}", [i] + at)
            self.props("observation_types", ob, "properties")
            self.emit("lukin ni li kama tan kute ni", [i, ob["source_binding"]])
            self.emit("lukin ni li tan lukin", [i])
        for c in p["constraints"]:
            i = c["id"]
            self.emit("awen ni li lon", [i])
            self.emit("ma ni la awen ni li lon", [c["scope"], i])
            self.emit("awen ni li tan nasin ni", [i, c["expression_ref"]])
            self.emit("awen ni li ken" + (" ala" if c["severity"] == "hard" else "") + " e weka", [i])

    def _output(self, i: str, te) -> None:
        ph, at, sub = self.type_phrase(te)
        self.emit(f"ilo ni li pana e {ph}", [i] + at)
        self.body.extend(sub)

    def action(self, ac: dict) -> None:
        i = ac["id"]
        self.emit("pali ni li lon", [i])
        self.params("pali", i, ac["inputs"])
        for r in ac["authority_refs"]:
            ph, at = self.ref(r, ("authority_rules",), AUTH_PREFIX)
            self.emit(f"pali ni li ken tan {ph}", [i] + at)
        for r in ac["policy_refs"]:
            ph, at = self.ref(r, ("policies",), POLICY_PREFIX)
            self.emit(f"pali ni li lawa tan {ph}", [i] + at)
        for c in ac["preconditions"]:
            self.emit("lon ni la pali ni li ken", [c, i])
        for e in ac["effects"]:
            self.effect(i, e)
        self.emit("pali ni li wile" + ("" if ac["idempotency"] == "required" else " ala") + " e sike sama", [i])
        self.emit("pali ni li kama e lon ni", [i, ac["outcome_predicate"]])
        if "compensation_action" in ac:
            ca = ac["compensation_action"]
            if ca is None:
                self.emit("pali ni li nasin weka e ala", [i])
            else:
                ph, at = self.ref(ca, ("actions",))
                self.emit(f"pali ni li nasin weka e {ph}", [i] + at)
        self.emit("tenpo ni la pali ni li lon", [ac["version"], i])

    def effect(self, i: str, e: dict) -> None:
        op = e["operation"]
        if op == "external_call":
            self.emit("pali ni li toki e ilo ni", [i, e["target"]])
        else:
            ph, at = self.ref(e["target"], EFFECT_KINDS[op])
            self.emit(f"pali ni li {EFFECT_VERB[op]} e {ph}", [i] + at)
        if "fields" in e and e["fields"] == []:
            self.emit("ante li ma e ala")
        for fld in e.get("fields", []):
            self.emit("ante li ma e sona ni", [fld])

    # ---------------------------------------------------------- metadata (a value block: opened, then closed)
    def meta_value(self, v, out: list) -> None:
        if isinstance(v, bool):
            out.append(("sitelen li sama e " + ("lon" if v else "lon ala"), []))
        elif v is None:
            out.append(("sitelen li sama e ala", []))
        elif isinstance(v, int):
            out.append(("sitelen li kulupu ijo li sama e ni", [str(v)]))
        elif isinstance(v, float):
            out.append(("sitelen li kulupu pilin li sama e ni", [json.dumps(v)]))
        elif isinstance(v, str):
            out.append(("sitelen li sitelen toki li sama e ni", [v]))
        elif isinstance(v, list):
            if not v:
                out.append(("sitelen li linja e ala", []))
                return
            for item in v:
                out.append(("sitelen li linja e sitelen", []))
                self.meta_value(item, out)
            out.append(("sitelen li pini", []))
        elif isinstance(v, dict):
            if not v:
                out.append(("sitelen li sona e ala", []))
                return
            for k, x in v.items():
                out.append(("sitelen li sona e sitelen ni", [k]))
                self.meta_value(x, out)
            out.append(("sitelen li pini", []))
        else:  # pragma: no cover - not JSON
            raise InvalidIR("metadata", f"not a JSON value: {type(v).__name__}")


def render(ir: dict) -> tuple[str, dict]:
    """(text, record): one OpenPona statement per line; record maps 'L<line>.a<slot>' to atom strings."""
    errs = validate(ir)
    if errs:
        raise InvalidIR("invalid_ir", "; ".join(str(e) for e in errs[:5]))
    check_representable(ir)
    r = _R(ir)
    head: list[tuple[str, list]] = [("kulupu ni li lon", [ir["package_id"]]),
                                    ("tenpo ni la kulupu li lon", [ir["version"]])]
    if "domain_id" in ir:
        head.append(("ma ni la kulupu li lon", [ir["domain_id"]]))
    if "imports" in ir and ir["imports"] == []:
        head.append(("kulupu li kute e ala", []))
    for s in ir.get("imports", []):
        head.append(("kulupu li kute e kulupu ni", [s]))
    if "metadata" in ir:
        md = ir["metadata"]
        if not md:
            head.append(("kulupu li sona e ala", []))
        for k, v in md.items():
            head.append(("kulupu li sona e sitelen ni", [k]))
            r.meta_value(v, head)
    r.resources()
    lines = head + r.body
    record: dict[str, str] = {}
    for n, (_, atoms) in enumerate(lines, 1):
        for j, a in enumerate(atoms, 1):
            record[f"L{n}.a{j}"] = a
    return "".join(t + "\n" for t, _ in lines), record
