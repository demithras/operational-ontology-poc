"""derive_verdict: the verdict is a pure function of frozen evidence + the experiment's registered evaluator.

The five booleans come from the evaluator registered for ``Experiment.evaluator_ref``; the verdict itself is always
``src/hdd/verdict.py:evaluate_common`` (never the evaluator's own verdict string, never user input).
"""
from __future__ import annotations

from typing import Callable

from paladin.domains._hdd.verdict import CommonEvaluation, evaluate_common

from paladin.domains._support import canonical_json, sha256_hex
from . import facts

FIELDS = ("protocol_valid", "required_evidence_complete", "sample_sufficient", "reject_hit", "support_hit")
Evaluator = Callable[[dict, list, dict], dict]  # (experiment, evidence rows, hypothesis) -> five booleans


class Deriver:
    def __init__(self, evaluators: dict[str, Evaluator]):
        self.evaluators = dict(evaluators)
        self._cache: dict = {}

    def derive(self, view, hid) -> dict:
        h = facts.props(view, "Hypothesis", hid)
        if h is None:
            raise KeyError(f"unknown hypothesis {hid!r}")
        eid = facts.latest_experiment(view, hid)
        if eid is None:  # nothing was ever tested: never SUPPORTED, never a guess
            common = dict(protocol_valid=True, required_evidence_complete=False, sample_sufficient=False,
                          reject_hit=False, support_hit=False)
            return self._result(common, hid, None, [], h)
        e = {"id": eid, **facts.props(view, "Experiment", eid)}
        ev = [{"id": k, **facts.props(view, "Evidence", k)} for k in facts.evidence_of_experiment(view, eid)
              if facts.props(view, "Evidence", k).get("experiment_version") == e.get("version")]
        if not ev:  # nothing attached to the latest experiment version: no evaluator is consulted, never SUPPORTED
            common = dict(protocol_valid=bool(h.get("freeze_hash")), required_evidence_complete=False,
                          sample_sufficient=False, reject_hit=False, support_hit=False)
            return self._result(common, hid, e, ev, h)
        if e.get("evaluator_ref") is None:  # a hidden/absent evaluator_ref behaves like null (PROT-H26 s3.3): nothing to consult
            common = dict(protocol_valid=bool(h.get("freeze_hash")), required_evidence_complete=False,
                          sample_sufficient=False, reject_hit=False, support_hit=False)
            return self._result(common, hid, e, ev, h)
        evaluator = self.evaluators.get(e["evaluator_ref"])
        if evaluator is None:
            raise LookupError(f"no evaluator registered for {e['evaluator_ref']!r}")
        key = canonical_json([e, sorted((x["id"], x.get("payload_hash"), x.get("git_commit")) for x in ev), h.get("freeze_hash"),
                              facts.evidence_count(view, hid)])
        if key not in self._cache:
            # P2a patch D4: the neutral evaluator needs evidence_count (SUPPORTS_OR_REFUTES links); passed as a plain value
            got = evaluator(e, ev, {"id": hid, **h, "_evidence_count": facts.evidence_count(view, hid)})
            if set(got) != set(FIELDS) or not all(isinstance(got[f], bool) for f in FIELDS):
                raise ValueError(f"evaluator for {e['evaluator_ref']!r} must return exactly {FIELDS} as booleans")
            self._cache[key] = got
        common = dict(self._cache[key])
        common["protocol_valid"] = common["protocol_valid"] and bool(h.get("freeze_hash"))
        return self._result(common, hid, e, ev, h)

    @staticmethod
    def _result(common: dict, hid, e, ev: list, h: dict) -> dict:
        verdict = evaluate_common(CommonEvaluation(**common)).value
        basis = {"hypothesis": hid, "experiment": None if e is None else [e["id"], e.get("version"), e.get("evaluator_ref")],
                 "evidence": sorted((x["id"], str(x.get("payload_hash"))) for x in ev), "common": common,
                 "freeze_hash": h.get("freeze_hash")}
        return {"verdict": verdict, "common": common, "experiment": None if e is None else e["id"],
                "evidence": [x["id"] for x in ev], "derivation_hash": sha256_hex(canonical_json(basis))}
