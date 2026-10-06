"""Registered experiment evaluators: ``Experiment.evaluator_ref`` -> callable(experiment, evidence rows, hypothesis).

The callable returns the five booleans ``derive_verdict`` feeds to ``src/hdd/verdict.py:evaluate_common``. The H15
evaluator is the real ``eoo_h15.evaluate.evaluate`` run over the COMMITTED evidence files of exactly the evidence rows
attached to the experiment (so an unattached file is missing evidence, and a row whose payload_hash differs from the
committed record invalidates the protocol).
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from eoo_h15.evaluate import evaluate

from .logic.freeze import BlobReader

FIELDS = ("protocol_valid", "required_evidence_complete", "sample_sufficient", "reject_hit", "support_hit")


def h15_evaluator(reader: BlobReader):
    def run(experiment: dict, evidence: list, hypothesis: dict) -> dict:
        exp_dir = f"experiments/h15/{experiment['id']}"
        mismatch = False
        with tempfile.TemporaryDirectory() as tmp:
            for ev in evidence:
                name = str(ev["id"]).split("/", 1)[-1]
                try:
                    blob = reader(f"{exp_dir}/{name}")
                    mismatch |= json.loads(blob).get("payload_hash") != ev["payload_hash"]
                except (FileNotFoundError, ValueError):
                    mismatch = True
                    continue
                (Path(tmp) / name).write_bytes(blob)
            got = evaluate(tmp)["common"]
        common = {f: bool(got[f]) for f in FIELDS}
        if mismatch:
            common["protocol_valid"] = False
        return common
    return run
