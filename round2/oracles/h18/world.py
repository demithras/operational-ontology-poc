"""H18 independent oracle: a pure model of ONE hypothesis' lifecycle world (docs/04 hard rules + the sanctioned paths).

Imports nothing from eoo_engine, eoo_toolchain, domains/* or the Project logic. Phase legality is decided by the named
reference model (src/hdd/project_lifecycle_reference.py); the rest (evidence pinning, verdict derivation for the
registered synthetic evaluator, orphan rule, versions, supersession) is written here from docs/04 alone.

``World(case).step(op) -> (legal, summary)``; an illegal op leaves the world unchanged. ``summary`` has the same keys
as ``summarize()`` over canonical artifact files, so the Engine, the baseline and the oracle compare field by field.
"""
from __future__ import annotations

from hdd import project_lifecycle_reference as ref

PINS_BAD = {"version": "version", "env": "environment", "commit": "commit", "hash": "hash"}
CORE_LINKS = ("rival", "prediction", "falsifier", "evaluator")


def expected_verdict(tags: list[str]) -> str:
    """Synthetic 'gen:evaluator' contract + pack-wide precedence (protocol_valid, reject, complete, support)."""
    n = len(tags)
    reject, complete, support = any(t == "r" for t in tags), n >= 2, n >= 1 and all(t == "s" for t in tags)
    if reject:
        return "REJECTED"
    if not complete:
        return "INCONCLUSIVE"
    return "SUPPORTED" if support else "INCONCLUSIVE"


class World:
    def __init__(self, case: dict):
        c, f = case, case["facts"]
        self.case, self.f = c, f
        self.phase = c["phase0"]
        self.freeze = None if self.phase == "DRAFT" else "fh-seed"
        self.complete = all(c["complete"][k] for k in CORE_LINKS)
        self.threshold = f["threshold_value"]
        self.ev = {e["id"]: e for e in c["evidence"]}
        self.attached: list[str] = []
        self.versions: list[str] = ["1"]
        self.verdicts: list[str] = []
        self.successor = None
        self.flagged: set = set()
        self.decided = False
        self.created: set = set()  # distinct non-blank claims
        self.superseded: set = set()

    # ---- reference model bridge ------------------------------------------------------------
    def _ref(self) -> ref.HypothesisState:
        return ref.HypothesisState(phase=ref.Phase(self.phase), has_claim=True, has_rival=self.complete, has_predictions=self.complete,
                                   has_falsifier=self.complete, has_evidence_schema=self.complete, has_evaluator=self.complete,
                                   freeze_hash=self.freeze, evidence_count=len(self.attached), threshold_revision=0)

    def _try(self, fn, *a, **k) -> bool:
        try:
            fn(*a, **k)
            return True
        except ref.InvalidTransition:
            return False

    def tags(self) -> list[str]:
        return [self.ev[i]["tag"] for i in self.attached]

    def orphans(self) -> set:
        sup = self.superseded
        links = {**self.f["components"], **{c["id"]: [self.case["subject"]] for c in self.case["components"]}}
        return {c for c, hs in links.items() if not [h for h in hs if h not in sup]}

    # ---- one op ----------------------------------------------------------------------------
    def step(self, op: dict) -> tuple[bool, dict]:
        legal = getattr(self, "_" + op["k"])(op)
        return legal, self.summary()

    def _preregister(self, op):
        fh = "" if op["freeze"] == "blank" else op["freeze_value"]
        if not self._try(ref.preregister, self._ref(), fh):
            return False
        self.phase, self.freeze = "PREREGISTERED", fh
        return True

    def _edit_threshold(self, op):
        if not self._try(ref.edit_threshold, self._ref()):
            return False
        self.threshold = op["value"]
        return True

    def _new_version(self, op):
        if self.phase in ("DRAFT", "SUPERSEDED"):  # DRAFT edits are free; SUPERSEDED is terminal (nothing follows it)
            return False
        target = "2" if op["exp"] == "base" else str(max(int(v) for v in self.versions) + 1)
        if target in self.versions:
            return False  # a version is never overwritten
        self.versions.append(target)
        return True

    def _start(self, op):
        if not self._try(ref.start, self._ref()):
            return False
        self.phase = "RUNNING"
        return True

    def _attach(self, op):
        e = self.ev[op["ev"]]
        pinned = e["pin"] == "good"  # version, environment, commit and payload hash all bound to the hypothesis' experiment
        if not self._try(ref.attach_evidence, self._ref(), commit_pinned=pinned):
            return False
        if e["id"] not in self.attached:
            self.attached.append(e["id"])
        return True

    def _evaluate(self, op):
        v = expected_verdict(self.tags())
        if not self._try(ref.evaluate, self._ref(), ref.ScientificVerdict(v)):
            return False
        self.phase = "EVALUATED"
        self.verdicts.append(v)
        return True

    def _forced_verdict(self, op):
        return False  # a verdict is machine-derived from frozen evidence + evaluator: never accepted as input

    def _supersede(self, op):
        succ = self.case["subject"] if op["succ"] == "self" else self.f["other"]
        if succ == self.case["subject"] or not self._try(ref.supersede, self._ref()):
            return False
        self.phase, self.successor = "SUPERSEDED", succ
        self.superseded.add(self.case["subject"])
        return True

    def _flag(self, op):
        if op["cmp"] not in self.orphans():
            return False
        self.flagged.add(op["cmp"])
        return True

    def _decision(self, op):
        if not str(self.case["decision"]["rationale"]).strip():
            return False
        self.decided = True
        return True

    def _create(self, op):
        if not str(op["claim"]).strip():
            return False
        self.created.add(str(op["claim"]).strip())
        return True

    # ---- observable summary ----------------------------------------------------------------
    def summary(self) -> dict:
        return {"phase": self.phase, "frozen": bool(str(self.freeze or "").strip()), "threshold": self.threshold,
                "attached": sorted(self.attached), "versions": sorted(self.versions), "verdicts": list(self.verdicts),
                "successor": self.successor, "flagged": sorted(self.flagged), "decided": self.decided,
                "created_n": len(self.created)}
