"""Change helpers: each builds the after-files of one lifecycle step; guards cover requests whose diff would be empty."""
from __future__ import annotations

import hashlib

from .derive import derive
from .repo import add_link, set_object
from .rules import owners_of_threshold


class Refused(Exception):
    pass


def need(cond, why):
    if not cond:
        raise Refused(why)


def phase(m, h):
    return m.props("Hypothesis", h)["phase"]


def preregister(files, m, h, freeze):
    need(phase(m, h) == "DRAFT", "only DRAFT may be preregistered")
    return set_object(files, "Hypothesis", h, {"phase": "PREREGISTERED", "freeze_hash": freeze})


def edit_threshold(files, m, t, value):
    need(all(phase(m, h) == "DRAFT" for h in owners_of_threshold(m, t)), "thresholds are immutable after preregistration")
    return set_object(files, "Threshold", t, {"value": value})


def new_version(files, m, exp, cv):
    old = m.props("Experiment", exp)
    ver = str(int(old["version"]) + 1)
    new_id = f"{exp.split('@v')[0]}@v{ver}"
    need(m.props("Experiment", new_id) is None, "a version is never overwritten")
    files = set_object(files, "Experiment", new_id, {"id": new_id, "version": ver, "evidence_schema_ref": old["evidence_schema_ref"], "evaluator_ref": old["evaluator_ref"]})
    cur = m.props("ContractVersion", cv)
    return set_object(files, "ContractVersion", f"{cv}+{ver}", {"id": f"{cv}+{ver}", "sha256": cur["sha256"], "git_commit": cur["git_commit"]})


def start(files, m, h):
    need(phase(m, h) == "PREREGISTERED", "only PREREGISTERED may start")
    return set_object(files, "Hypothesis", h, {"phase": "RUNNING"})


def attach(files, m, h, ev):
    need(phase(m, h) == "RUNNING", "evidence attaches only while RUNNING")
    exp = next((e for e in m.out("TESTED_BY", h) if m.props("Experiment", e)["version"] == m.props("Evidence", ev)["experiment_version"]), None)
    need(exp is not None, "evidence is bound to no version of an experiment of this hypothesis")
    return add_link(add_link(files, "PRODUCES", ("Experiment", exp), ("Evidence", ev)), "SUPPORTS_OR_REFUTES", ("Evidence", ev), ("Hypothesis", h))


def _verdict(files, m, h, value, commit):
    vid = f"verdict-{h}-{len([v for v in m.keys('Verdict') if ('EVALUATES', v, h) in m.links]) + 1}"
    props = {"id": vid, "value": value, "reason": "derived", "derivation_hash": hashlib.sha256(f"{h}{value}".encode()).hexdigest(), "git_commit": commit}
    files = set_object(files, "Verdict", vid, props)
    return add_link(set_object(files, "Hypothesis", h, {"phase": "EVALUATED"}), "EVALUATES", ("Verdict", vid), ("Hypothesis", h))


def evaluate(files, m, h, commit, evaluators):
    need(phase(m, h) == "RUNNING", "only RUNNING can be evaluated")
    return _verdict(files, m, h, derive(m, h, evaluators), commit)


def forced_verdict(files, m, h, commit, value):
    return _verdict(files, m, h, value, commit)


def supersede(files, m, h, succ):
    need(phase(m, h) == "EVALUATED", "only EVALUATED may be superseded")
    return add_link(set_object(files, "Hypothesis", h, {"phase": "SUPERSEDED"}), "SUPERSEDED_BY", ("Hypothesis", h), ("Hypothesis", succ))


def flag(files, m, c):
    return set_object(files, "Component", c, {"orphan_flagged": True})


def decide(files, m, d, cv):
    return add_link(files, "CHANGES", ("Decision", d), ("ContractVersion", cv))


def create(files, m, claim):
    hid = "hyp-" + hashlib.sha256(claim.encode()).hexdigest()[:10]
    return set_object(files, "Hypothesis", hid, {"id": hid, "claim": claim, "phase": "DRAFT"})
