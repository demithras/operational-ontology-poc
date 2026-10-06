"""Compiler mutants of the H15 v2 candidate (src/eoo_openpona2), the same target classes as mutants.MUTANTS["openpona"].

Each function injects one known defect by monkeypatch; mutants.suite must notice it (see mutants.py)."""
from __future__ import annotations

import eoo_openpona2.compiler as op2_compiler
import eoo_openpona2.ctx as ctx2
import eoo_openpona2.document as document2
import eoo_openpona2.lines as lines2
import eoo_openpona2.resources as resources2
from eoo_openpona2.errors import Invalid


def drop_cardinality(mp):
    mp.setattr(ctx2._C, "card", lambda self, k, side: {"min": 0, "max": "*"})


def swap_function_action(mp):
    mp.setitem(document2.HEAD_KIND, "ilo", "actions")
    mp.setitem(document2.HEAD_KIND, "pali", "functions")


def drop_authority_ref(mp):
    o = resources2._action
    mp.setattr(resources2, "_action", lambda c, k, p: {**o(c, k, p), "authority_refs": []})


def drop_version(mp):
    o = ctx2._C.one
    mp.setattr(ctx2._C, "one", lambda self, k, f, required=True: "v" if f == "version" else o(self, k, f, required))


def accept_ambiguous_binding(mp):
    mp.setattr(op2_compiler, "_check_ir", lambda c, ir: None)  # denotation / ambiguous_ref checks switched off


def default_missing_type(mp):
    o = ctx2._C.one

    def one(self, k, f, required=True):
        try:
            return o(self, k, f, required)
        except Invalid as e:
            if f == "type" and e.code == "missing:type":
                return ("prim", "string")  # DEFECT: invents a type
            raise
    mp.setattr(ctx2._C, "one", one)


def default_immutable_false(mp):  # extra (not a registered target class)
    o = ctx2._C.prop
    mp.setattr(ctx2._C, "prop", lambda self, k, path: {"immutable": False, **o(self, k, path)})


def accept_parse_ambiguity(mp):  # extra: parser AMBIGUOUS -> pick the first skeleton
    real = lines2.parsed

    class _R:
        def __init__(self, r):
            self.__dict__.update({k: getattr(r, k) for k in dir(r) if not k.startswith("_")})

    def parsed(text):
        r = real(text)
        if r.status == "AMBIGUOUS":
            x = _R(r)
            x.status, x.skeletons = "RESOLVED", [r.skeletons[0]]
            return x
        return r
    mp.setattr(lines2, "parsed", parsed)


def auto_close_metadata(mp):  # extra, v2-specific: open metadata values closed instead of refused
    real = document2.MetaReader.result

    def result(self, last_line):
        while self.stack:  # DEFECT: closes open values instead of refusing an unclosed block
            top = self.stack[-1]
            self._done(top, top.value)
        return real(self, last_line)
    mp.setattr(document2.MetaReader, "result", result)


MUTANTS = {"drop_cardinality": drop_cardinality, "swap_function_action": swap_function_action,
           "drop_authority_ref": drop_authority_ref, "drop_version": drop_version,
           "accept_ambiguous_binding": accept_ambiguous_binding, "default_missing_type": default_missing_type}
EXTRAS = {"default_immutable_false": default_immutable_false, "accept_parse_ambiguity": accept_parse_ambiguity,
          "auto_close_metadata": auto_close_metadata}
