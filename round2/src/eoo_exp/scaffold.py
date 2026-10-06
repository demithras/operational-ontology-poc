"""Evaluator scaffold shared by H16-H22: evidence loading + clause tables + hdd.verdict.evaluate_common."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

import jsonschema

from hdd.verdict import CommonEvaluation, evaluate_common

from .provenance import freeze_hash, prereg_sha
from .util import ROOT, canon, sha_text


def load_evidence(d: Path, hid: str, required: list[str], root: Path = ROOT) -> tuple[dict, dict, list]:
    """(records, payloads, problems). A missing / unparsable / schema-invalid / hash-mismatching file is a problem."""
    schema = json.loads((root / "schemas/evidence-record.schema.json").read_text())
    recs, pay, problems = {}, {}, []
    for f in required:
        p = Path(d) / f
        if not p.is_file():
            problems.append(f"{f}: missing")
            continue
        try:
            r = json.loads(p.read_text())
            jsonschema.validate(r, schema)
            if r["hypothesis_id"] != hid or r["evidence_kind"] != f[:-5]:
                raise ValueError(f"hypothesis_id/evidence_kind {r['hypothesis_id']}/{r['evidence_kind']}")
            if "payload" not in r or sha_text(canon(r["payload"])) != r["payload_hash"]:
                raise ValueError("payload_hash does not match the payload")
        except Exception as e:  # noqa: BLE001 - any defect makes the file unusable evidence
            problems.append(f"{f}: unreadable/invalid ({type(e).__name__}: {str(e)[:120]})")
            continue
        recs[f], pay[f] = r, r["payload"]
    return recs, pay, problems


def g(x, *path, default=None):
    """Safe nested get over dicts/lists."""
    for p in path:
        if not isinstance(x, (dict, list)):
            return default
        try:
            x = x[p]
        except (KeyError, IndexError, TypeError):
            return default
    return x


def rows(table: dict, vals: dict) -> list[dict]:
    """Clause table: one named predicate per contract clause, value True/False/None (None = unknown)."""
    return [{"id": k, "clause": t, "value": vals[k]} for k, t in table.items()]


def protocol_state(recs: dict, root: Path = ROOT) -> tuple[list, list]:
    """(records with wrong freeze/prereg hash, distinct provenance tuples) against the files as they are NOW."""
    fz, pre = freeze_hash(), prereg_sha()
    wrong = [f for f, r in recs.items() if (r["protocol_freeze_hash"], r.get("engine_prereg_sha256")) != (fz, pre)]
    ident = {(r["git_commit"], r.get("seed"), r.get("input_corpus_hash"), r["experiment_id"]) for r in recs.values()}
    return wrong, sorted(ident, key=str)


def finish(hid: str, exp_id: Optional[str], *, protocol_valid: bool, complete: bool, sample_sufficient: bool,
           reject_hit: bool, support_hit: bool, predicates: dict, numbers: dict, problems: list,
           extra: dict | None = None) -> dict:
    common = CommonEvaluation(protocol_valid=protocol_valid, required_evidence_complete=complete,
                              sample_sufficient=sample_sufficient, reject_hit=reject_hit, support_hit=support_hit)
    verdict = evaluate_common(common)
    return {"experiment_id": exp_id, "hypothesis_id": hid, "verdict": verdict.value,
            "common": {"protocol_valid": protocol_valid, "required_evidence_complete": complete,
                       "sample_sufficient": sample_sufficient, "reject_hit": reject_hit, "support_hit": support_hit},
            "predicates": predicates, "numbers": numbers, "problems": problems, **(extra or {})}
