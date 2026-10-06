"""Independent capability reference model for H21 (written from docs/engine_semantics.md sections 5 and 8; imports nothing
from the Engine, the Toolchain or domain packs).

Input: a raw IR dict and a *case* {"principal": plain principal, "registered": bool, "world": {"objects": {type: [keys]},
"flags": {"preregistered": [keys], "fault": bool}}}. Output: the capability sets a correct surface must expose.
"""
from __future__ import annotations

import itertools
import json


class Reference:
    def __init__(self, ir: dict):
        self.ir = ir
        self.obj = {o["id"]: o for o in ir["object_types"]}
        self.ifaces = {i["id"] for i in ir["interfaces"]}
        self.links = {x["id"] for x in ir["link_types"]}
        self.rules = {r["id"]: r for r in ir["authority_rules"]}
        self.actions = {a["id"]: a for a in ir["actions"]}
        self.impl = {i: sorted(t for t, o in self.obj.items() if i in o.get("implements", [])) for i in self.ifaces}

    # ---- name resolution ----------------------------------------------------------------------------------------
    def resolve(self, name: str):
        hits = {n for n in list(self.obj) + sorted(self.ifaces) + sorted(self.links) if n.lower() == name.lower()}
        return next(iter(hits)) if len(hits) == 1 else None

    def conforms(self, actual: str, declared: str) -> bool:
        return actual == declared or actual in self.impl.get(declared, [])

    # ---- opaque selectors (the reference model's own, domain-agnostic reading of the two texts the domains use) -----
    def opaque(self, text: str, resources: list, flags: dict):
        if flags.get("fault"):
            raise RuntimeError("selector fault")
        if text == "ProjectOntology:*":
            own = set(self.obj) | self.links
            return bool(resources) and all(r["actual"] in own for r in resources)
        if text == "Threshold:preregistered":
            return any(r["actual"] == "Threshold" and r["key"] is not None and r["key"] in flags.get("preregistered", [])
                       for r in resources)
        raise LookupError(text)

    # ---- selectors -----------------------------------------------------------------------------------------------
    def who_matches(self, sel: str, who: dict, resources: list, flags: dict) -> bool:
        if sel == "*":
            return True
        if sel.startswith("role:") and len(sel) > 5:
            return sel[5:] in who["roles"]
        if sel.startswith("principal:") and len(sel) > 10:
            return sel[10:] == who["pid"]
        if "#" in sel:
            t, rel = sel.split("#", 1)
            rt = self.resolve(t) if t and rel else None
            if rt:
                held = {tuple(x) for x in who["relations"]}
                bound = [r for r in resources if r["key"] is not None and self.conforms(r["actual"], rt)]
                return len(bound) > 0 and all((r["actual"], r["key"], rel) in held for r in bound)
        return self.opaque(sel, resources, flags)

    def res_matches(self, sel: str, resources: list, flags: dict) -> bool:
        if sel == "*":
            return True
        if sel.endswith(":*") and len(sel) > 2:
            rt = self.resolve(sel[:-2])
            if rt:
                return any(r["declared"] == rt or self.conforms(r["actual"], rt) for r in resources)
        return self.opaque(sel, resources, flags)

    @staticmethod
    def cap_matches(pattern: str, cap: str) -> bool:
        return pattern == cap or pattern == "*" or (pattern.endswith(":*") and cap.startswith(pattern[:-1]))

    # ---- decision ------------------------------------------------------------------------------------------------
    def grant(self, refs: list, who: dict, cap: str, resources: list, flags: dict, depth: int = 0) -> tuple:
        """(allowed, failed). failed = some selector could not be evaluated (or a ref is import-qualified)."""
        if depth > 16:
            return False, True
        allows = denies = failed = False
        for ref in refs:
            rid = ref[5:] if ref.startswith("auth:") else None
            rule = self.rules.get(rid)
            if rule is None:
                failed = True
                continue
            if not self.cap_matches(rule["capability"], cap):
                continue
            try:
                if rule["effect"] == "deny":
                    link, w = [], who
                    while w is not None:
                        link.append(w)
                        w = w["delegated_by"]
                    if any(self.who_matches(rule["principal_selector"], w, resources, flags)
                           and self.res_matches(rule["resource_selector"], resources, flags) for w in link):
                        denies = True
                elif self.who_matches(rule["principal_selector"], who, resources, flags) and \
                        self.res_matches(rule["resource_selector"], resources, flags):
                    if who["delegated_by"] is None:
                        allows = True
                    elif rule.get("delegation_allowed"):
                        ok, bad = self.grant(refs, who["delegated_by"], cap, resources, flags, depth + 1)
                        failed = failed or bad
                        allows = allows or ok
            except Exception:  # noqa: BLE001 - fail closed
                failed = denies = True
        return (allows and not denies and not failed), failed

    # ---- bindings ------------------------------------------------------------------------------------------------
    def candidates(self, declared: str, objects: dict) -> list:
        types = [declared] if declared in self.obj else self.impl.get(declared, [])
        return [(k, t) for t in types for k in objects.get(t, [])]

    def ref_inputs(self, action: dict) -> list:
        out = []
        for p in action["inputs"]:
            te, is_list, optional = p["type"], False, not p.get("required", True)
            while isinstance(te, dict):
                (c, inner), = te.items()
                if c == "ref":
                    out.append((p["name"], inner, is_list, optional))
                    break
                is_list, optional = (is_list or c == "list"), (optional or c == "optional")
                te = inner
        return out

    def bindings(self, action: dict, objects: dict):
        slots = self.ref_inputs(action)
        pools = [([None] if opt else []) + self.candidates(decl, objects) for _n, decl, _l, opt in slots]
        targets = [{"declared": e["target"], "key": None, "actual": e["target"]} for e in action["effects"]]
        for combo in (itertools.product(*pools) if slots else [()]):
            b, res = {}, []
            for (name, decl, is_list, _o), pick in zip(slots, combo):
                if pick is None:
                    continue
                k, actual = pick
                b[name] = [k] if is_list else k
                res.append({"declared": decl, "key": k, "actual": actual})
            yield b, res + targets

    # ---- capability sets -----------------------------------------------------------------------------------------
    def sets(self, case: dict) -> dict:
        if not case["registered"]:
            return {"visible": [], "queryable": [], "actionable": [], "approvable": [], "tools": []}
        who, objects, flags = case["principal"], case["world"]["objects"], case["world"]["flags"]
        visible = sorted(set(self.obj) | self.ifaces | self.links)
        queryable = sorted([f"get:{t}" for t in self.obj] + [f"list:{t}" for t in self.obj] + [f"query:{i}" for i in self.ifaces]
                           + [f"follow:{x}" for x in self.links] + [f"call:{f['id']}" for f in self.ir["functions"]])
        actionable, approvable = [], []
        for aid, a in sorted(self.actions.items()):
            approvals = sorted({self.rules[r[5:]]["capability"] for r in a["authority_refs"] if r.startswith("auth:")
                                and r[5:] in self.rules and self.rules[r[5:]]["effect"] == "allow"
                                and self.rules[r[5:]]["capability"].startswith("approval:")})
            for b, res in self.bindings(a, objects):
                bk = json.dumps(b, sort_keys=True, separators=(",", ":"))
                if self.grant(a["authority_refs"], who, "action:" + aid, res, flags)[0]:
                    actionable.append(f"{aid}|{bk}")
                approvable += [f"{aid}|{c}|{bk}" for c in approvals if self.grant(a["authority_refs"], who, c, res, flags)[0]]
        granted = {x.split("|", 1)[0] for x in actionable}
        tools = ([f"get_{t}" for t in self.obj] + [f"list_{t}" for t in self.obj] + [f"query_{i}" for i in self.ifaces]
                 + [f"follow_{x}" for x in self.links] + [f"call_{f['id']}" for f in self.ir["functions"]]
                 + [f"act_{a}" for a in sorted(granted)])
        return {"visible": visible, "queryable": queryable, "actionable": sorted(set(actionable)),
                "approvable": sorted(set(approvable)), "tools": sorted(tools)}
