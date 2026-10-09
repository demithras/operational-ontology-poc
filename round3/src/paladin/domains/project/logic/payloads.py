"""Effect payloads of the Project Ontology actions: what each governed Git change would write.

One function per action returns the list of payloads in IR effect order. The Engine's ``payload`` bindings and the
outcome predicates (which compare Git's answer with what was supposed to be written) use the same function, so the
expectation is derived from the action's own inputs and the read view, never from the adapter's response.
Reserved keys follow the Engine: ``$key`` (object key), ``$src`` / ``$dst`` (link ends).
"""
from __future__ import annotations

from paladin.domains._support import parse_dt, sha256_hex
from . import facts


def head_commit(view) -> str:
    """The most recent Commit the ontology knows (the Git head it was last synchronised to)."""
    cs = [(r["props"].get("committed_at"), r["key"]) for r in view.list("Commit")]  # P2a patch D2: integer ticks
    cs = [c for c in cs if isinstance(c[0], int) and not isinstance(c[0], bool)]
    if not cs:
        raise LookupError("no Commit with committed_at in the ontology: cannot bind a git_commit")
    return max(cs)[1]


def next_version(v: str) -> str:
    return str(int(v) + 1) if str(v).isdigit() else f"{v}.1"


def _verdict_ids(view, hid) -> list:
    return facts.inn(view, "EVALUATES", "Hypothesis", hid)


def create_hypothesis(ctx, deriver, reader):
    return [{"id": "hyp-" + sha256_hex(ctx.inputs["claim"])[:10], "claim": ctx.inputs["claim"], "phase": "DRAFT"}]


def edit_threshold(ctx, deriver, reader):
    return [{"value": ctx.inputs["value"], "$key": ctx.inputs["threshold"]}]


def preregister_hypothesis(ctx, deriver, reader):
    return [{"phase": "PREREGISTERED", "freeze_hash": ctx.inputs["freeze_hash"], "$key": ctx.inputs["hypothesis"]}]


def new_experiment_ids(view, inputs) -> tuple:
    """(old experiment id, new experiment id, new version, new contract-version id)."""
    old_id = inputs["experiment"]
    ver = next_version(facts.props(view, "Experiment", old_id)["version"])
    return old_id, f"{str(old_id).split('@v')[0]}@v{ver}", ver, f"{inputs['contract_version']}+{ver}"


def new_experiment_version(ctx, deriver, reader):
    old_id, new_id, ver, cv_id = new_experiment_ids(ctx.view, ctx.inputs)
    old = facts.props(ctx.view, "Experiment", old_id)
    return [{"id": new_id, "version": ver, "evidence_schema_ref": old["evidence_schema_ref"],
             "evaluator_ref": old["evaluator_ref"]},
            {"id": cv_id, "sha256": ctx.call("compute_freeze_hash", {"experiment": old_id}),
             "git_commit": head_commit(ctx.view)},
            {"$src": new_id, "$dst": old_id}]  # v3 effect #2: NEW_VERSION_OF (new version -> its predecessor)


def start_run(ctx, deriver, reader):
    return [{"phase": "RUNNING", "$key": ctx.inputs["hypothesis"]}]


def experiment_of_evidence(view, hid, evidence_props):
    """The hypothesis' experiment whose version the evidence is pinned to (exactly one, else None)."""
    hits = [e for e in facts.experiments_of(view, hid)
            if (facts.props(view, "Experiment", e) or {}).get("version") == (evidence_props or {}).get("experiment_version")]
    return hits[0] if len(hits) == 1 else None


def attach_evidence(ctx, deriver, reader):
    ev_id = ctx.inputs["evidence"]
    ev = facts.props(ctx.view, "Evidence", ev_id)
    exp = experiment_of_evidence(ctx.view, ctx.inputs["hypothesis"], ev)
    if exp is None:
        raise ValueError("evidence is not pinned to a version of an experiment of this hypothesis")
    return [{"id": ev_id, **{k: ev[k] for k in ("payload_hash", "git_commit", "experiment_version", "environment")}},
            {"$src": exp, "$dst": ev_id},
            {"$src": ev_id, "$dst": ctx.inputs["hypothesis"]}]  # v2 effect #2: SUPPORTS_OR_REFUTES


def evaluate_hypothesis(ctx, deriver, reader):
    hid = ctx.inputs["hypothesis"]
    d = deriver.derive(ctx.view, hid)
    vid = f"verdict-{hid}-{len(_verdict_ids(ctx.view, hid)) + 1}"
    reason = (f"machine-derived by evaluate_common from experiment {d['experiment']} over {len(d['evidence'])} "
              f"evidence record(s): {d['common']}")
    return [{"id": vid, "value": d["verdict"], "reason": reason, "derivation_hash": d["derivation_hash"],
             "git_commit": head_commit(ctx.view), "$hypothesis": hid},
            {"phase": "EVALUATED", "$key": hid}, {"$src": vid, "$dst": hid}]


def supersede_hypothesis(ctx, deriver, reader):
    return [{"phase": "SUPERSEDED", "$key": ctx.inputs["hypothesis"]},
            {"$src": ctx.inputs["hypothesis"], "$dst": ctx.inputs["successor"]}]


def record_decision(ctx, deriver, reader):
    d = facts.props(ctx.view, "Decision", ctx.inputs["decision"])
    row = {"id": ctx.inputs["decision"], "rationale": d["rationale"]}
    if d.get("decided_at") is not None:
        row["decided_at"] = d["decided_at"]
    return [row, {"$src": ctx.inputs["decision"], "$dst": ctx.inputs["contract_version"]}]


def flag_orphan_component(ctx, deriver, reader):
    return [{"orphan_flagged": True, "$key": ctx.inputs["component"]}]


PAYLOAD_FNS = {f.__name__: f for f in (create_hypothesis, edit_threshold, preregister_hypothesis, new_experiment_version,
                                       start_run, attach_evidence, evaluate_hypothesis, supersede_hypothesis,
                                       record_decision, flag_orphan_component)}
