"""Provenance envelope (Engine v1.2): the Engine, never an adapter, composes the provenance of every effect it hands out.

For each effect routed to an adapter the Engine builds a read-only ``ProvenanceEnvelope`` and its canonical text
``render_envelope(env)``. The adapter receives both inside the effect request (``effect["envelope"]`` /
``effect["envelope_text"]``) and may only write the text verbatim into the external system (a Git commit message).
Facts about the external system (commit, base, head at write, merge mode, state digest, writer) come back as the
adapter's RESPONSE; the Engine records them in its ProvenanceLog next to the envelope.

Canonical text (stable, deterministic; see docs/engine_semantics.md section 9)::

    <action>: <execution> <effect_id>          subject line (informative; parsers ignore it)
    <empty line>
    EOO-Envelope: 1
    EOO-Execution: "x1"                        one line per field, in FIELDS order,
    ...                                        value = canonical JSON (ASCII, sorted keys, no spaces)

Every value is one JSON token, so no value can break a line or forge another field. The text ends with one newline.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, fields
from typing import Any, Optional

ENVELOPE_VERSION = 1
# (field name, label) in rendering order
FIELDS = (("envelope_version", "EOO-Envelope"), ("execution", "EOO-Execution"), ("action", "EOO-Action"),
          ("action_version", "EOO-Action-Version"), ("package", "EOO-Package"), ("engine_version", "EOO-Engine-Version"),
          ("principal", "EOO-Principal"), ("delegated_by", "EOO-Delegated-By"), ("idempotency_key", "EOO-Idempotency-Key"),
          ("effect_id", "EOO-Effect"), ("operation", "EOO-Operation"), ("target", "EOO-Target"),
          ("execution_effects", "EOO-Execution-Effects"))
LABELS = {f: lab for f, lab in FIELDS}
_BY_LABEL = {lab: f for f, lab in FIELDS}


@dataclass(frozen=True)
class ProvenanceEnvelope:
    envelope_version: int
    execution: str
    action: str
    action_version: Any
    package: str
    engine_version: str
    principal: Optional[str]
    delegated_by: Optional[str]
    idempotency_key: Optional[str]
    effect_id: str
    operation: str
    target: str
    execution_effects: tuple  # ((effect_id, operation, target), ...) of every adapter-routed effect of the execution

    @classmethod
    def from_plain(cls, d: dict) -> "ProvenanceEnvelope":
        return cls(**{**d, "execution_effects": tuple(tuple(x) for x in d["execution_effects"])})

    def to_plain(self) -> dict:
        out = {f.name: getattr(self, f.name) for f in fields(self)}
        out["execution_effects"] = [list(x) for x in self.execution_effects]
        return out


def _value(v: Any) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _subject_part(v: Any) -> str:
    return _value(str(v))[1:-1]  # JSON-escaped, unquoted: never contains a newline


def render_envelope(env: ProvenanceEnvelope) -> str:
    plain = env.to_plain()
    subject = f"{_subject_part(env.action)}: {_subject_part(env.execution)} {_subject_part(env.effect_id)}"
    body = "\n".join(f"{lab}: {_value(plain[f])}" for f, lab in FIELDS)
    return subject + "\n\n" + body + "\n"


def parse_envelope(text: str) -> dict:
    """Envelope text (or a commit message equal to it) -> {field: value}. Unknown / malformed lines are ignored;
    a message without an envelope gives {}."""
    out: dict = {}
    for ln in text.splitlines():
        lab, sep, raw = ln.partition(": ")
        if sep and lab in _BY_LABEL:
            try:
                out[_BY_LABEL[lab]] = json.loads(raw)
            except ValueError:
                continue
    return out


def build_envelope(rec: dict, spec, eff, adapter_effects: list, engine_version: str) -> ProvenanceEnvelope:
    """Snapshot of the Engine's own record of the execution at the moment the effect is handed to an adapter."""
    who = rec.get("principal") or {}
    deleg = who.get("delegated_by") or {}
    ex = rec["exec"]
    return ProvenanceEnvelope(
        envelope_version=ENVELOPE_VERSION, execution=ex, action=spec.rid, action_version=rec.get("action_version"),
        package=f"{rec.get('package_id')}@{rec.get('package_version')}", engine_version=engine_version,
        principal=who.get("pid"), delegated_by=deleg.get("pid"), idempotency_key=rec.get("key"),
        effect_id=f"{ex}/e{eff.index}", operation=eff.operation, target=eff.target,
        execution_effects=tuple((f"{ex}/e{e.index}", e.operation, e.target) for e in adapter_effects))
