"""Which OpenPona candidate the H15 harness drives.

'openpona'  = H15 v1 candidate (src/eoo_openpona, pinned by protocol/H15_CANDIDATE.json; exp-h15-001/002).
'openpona2' = H15 v2 candidate (src/eoo_openpona2, protocol/H15_V2_PREREG.json; pin protocol/H15_V2_CANDIDATE.json).

The oracle, generator, DSL baseline, ambiguity classes and contract clauses are the same objects for both; only the
candidate surface and the v2 audit steps (sidecar audit_procedure_v2, meaning rule) differ. The default is v1, so
every caller that never calls use() behaves exactly as before.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from types import ModuleType
from typing import Callable

import eoo_openpona
import eoo_openpona.compiler as op_compiler
import eoo_openpona2
import eoo_openpona2.compiler as op2_compiler

from .util import ROOT


@dataclass(frozen=True)
class Candidate:
    name: str
    pkg: ModuleType                # render / load_record / dump_record / OpenPonaError
    compiler: ModuleType           # .compile(text, record, check_ir=True)
    cases: str                     # declared ambiguity cases (jsonl, relative to round2/)
    domain_op: str                 # domains/<d>/<domain_op>
    domain_rec: str
    pin: str                       # candidate pin file (relative to round2/)
    files: Callable[[], list[str]]  # files the pin covers


def _v1_files() -> list[str]:
    return [e["path"] for e in json.loads((ROOT / "protocol/H15_CANDIDATE.json").read_text())["files"]]


def v2_files() -> list[str]:
    src = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "src/eoo_openpona2").glob("*.py"))
    return [f"domains/{d}/{n}" for d in ("manufacturing", "project") for n in ("openpona2.op", "openpona2.record.json")] + \
        ["ontology/openpona2_encoding.md", "ontology/openpona2_gaps.json"] + src


V1 = Candidate("openpona", eoo_openpona, op_compiler, "tests/h15/openpona_ambiguity_cases.jsonl", "openpona.op",
               "openpona.record.json", "protocol/H15_CANDIDATE.json", _v1_files)
V2 = Candidate("openpona2", eoo_openpona2, op2_compiler, "tests/h15/openpona2_ambiguity_cases.jsonl", "openpona2.op",
               "openpona2.record.json", "protocol/H15_V2_CANDIDATE.json", v2_files)
CANDIDATES = {"openpona": V1, "openpona2": V2}
_ACTIVE = {"name": "openpona", "pin": None}


def current() -> Candidate:
    return CANDIDATES[_ACTIVE["name"]]


def is_v2() -> bool:
    return _ACTIVE["name"] == "openpona2"


def pin_path():
    """The candidate pin file in force (an explicit override, else the candidate's default under protocol/)."""
    from pathlib import Path
    return Path(_ACTIVE["pin"]) if _ACTIVE["pin"] else ROOT / current().pin


def use(name: str, pin: str | None = None) -> Candidate:
    """Switch the harness to candidate `name` (and an optional pin file override). Returns the candidate."""
    from . import surfaces
    if name not in CANDIDATES:
        raise ValueError(f"unknown surface {name!r}; one of {sorted(CANDIDATES)}")
    _ACTIVE["name"], _ACTIVE["pin"] = name, pin
    surfaces.SURFACES["openpona"] = surfaces.OPENPONA2 if name == "openpona2" else surfaces.OPENPONA
    return current()
