"""TC3: Replication objects (props id, experiment_ref, outcome), REPLICATES links, register/count helpers and the rule."""
from __future__ import annotations

from .actions import need
from .repo import add_link, set_object


def violations(b, a, ev):
    return [f"{r}: replication of an experiment whose hypothesis is not EVALUATED"
            for r in a.keys("Replication") if b.props("Replication", r) is None
            and not all(b.props("Hypothesis", h)["phase"] == "EVALUATED" for h in b.inn("TESTED_BY", a.props("Replication", r)["experiment_ref"]))]


def register(files, m, rid, exp, outcome):
    need(m.props("Experiment", exp) is not None, "unknown experiment")
    files = set_object(files, "Replication", rid, {"id": rid, "experiment_ref": exp, "outcome": outcome})
    return add_link(files, "REPLICATES", ("Replication", rid), ("Experiment", exp))


def count(m, exp):
    return len(m.inn("REPLICATES", exp))
