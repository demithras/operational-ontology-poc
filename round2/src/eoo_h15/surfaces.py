"""Uniform adapters over the two surfaces. Every compile goes through the module attribute so that the
mutation harness (monkeypatch) is seen by every check."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import eoo_dsl
import eoo_dsl.compiler as dsl_compiler
import eoo_openpona
import eoo_openpona.compiler as op_compiler
from eoo_dsl import DslError
from eoo_openpona import OpenPonaError, Unrepresentable


@dataclass(frozen=True)
class Surface:
    name: str
    render: Callable[[dict], Any]          # IR -> artifact (may raise)
    compile: Callable[[Any], dict]         # artifact -> IR (may raise typed error)
    typed_errors: tuple                    # the typed failure family
    unrepresentable: tuple = ()            # render-time "this IR construct is not representable"

    def family(self, e: BaseException) -> str:
        return type(e).__name__


def _op_compile(art):
    text, rec = art
    return op_compiler.compile(text, rec)


def _dsl_compile(text):
    return dsl_compiler.compile(text)


OPENPONA = Surface("openpona", eoo_openpona.render, _op_compile, (OpenPonaError,), (Unrepresentable,))
DSL = Surface("dsl", eoo_dsl.render, _dsl_compile, (DslError,), ())
SURFACES = {"openpona": OPENPONA, "dsl": DSL}


def artifact_text(name: str, art) -> str:
    return art[0] + "\n" + _record_text(art[1]) if name == "openpona" else art


def _record_text(rec: dict) -> str:
    return eoo_openpona.dump_record(rec)
