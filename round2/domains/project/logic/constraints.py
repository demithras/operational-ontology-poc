"""Constraint expression bindings of the Project Ontology (pred(ctx) -> bool, True = holds on the would-be state).

Durable changes are Git changes, so the would-be state is the store plus ``ctx.planned`` (the payloads about to be
written to Git). Each invariant is checked on that union. Invariants about the store alone (rebuild hash, ...) are
marked weak in provenance-logic.md.
"""
from __future__ import annotations

from domains._support import canonical_json, sha256_hex
from . import facts
from .lifecycle import legal_transition
from .policies import contract_complete

STATE_TYPES = ("Hypothesis", "Rival", "Prediction", "Falsifier", "Experiment", "Metric", "Threshold", "Evidence",
               "Verdict", "Component", "ContractVersion", "Commit", "Test", "Decision", "Failure")


def state_hash(view, reverse: bool = False) -> str:
    rows = []
    for t in STATE_TYPES:
        recs = list(view.list(t))
        for r in (reversed(recs) if reverse else recs):
            rows.append([t, r["key"], dict(r["props"])])
    return sha256_hex(canonical_json(sorted(rows, key=lambda x: (x[0], str(x[1])))))


def _blank(v) -> bool:
    return not str(v if v is not None else "").strip()


def make(ir: dict, deriver) -> dict:
    types = {t["id"]: t for t in ir["object_types"]}
    fields_of = {(a["id"], i): (None if "fields" not in e else tuple(e["fields"]))
                 for a in ir["actions"] for i, e in enumerate(a["effects"])}

    def verdict_rows(ctx):
        """(id, value, hypothesis, reason, derivation_hash, stored) for stored and planned Verdicts."""
        rows = []
        for r in ctx.view.list("Verdict"):
            hs = facts.out(ctx.view, "EVALUATES", "Verdict", r["key"])
            rows.append((r["key"], r["props"].get("value"), hs[0] if hs else None, r["props"].get("reason"),
                         r["props"].get("derivation_hash"), True))
        for p in facts.planned(ctx, "Verdict"):
            rows.append((p.get("id"), p.get("value"), p.get("$hypothesis"), p.get("reason"), p.get("derivation_hash"), False))
        return rows

    def supported_needs_evidence(ctx):
        return all(facts.evidence_count(ctx.view, h) >= 1 for _, v, h, *_ in verdict_rows(ctx) if v == "SUPPORTED")

    def prereg_complete(ctx):
        return all(contract_complete(ctx.view, h) for h, p in facts.effective_hypotheses(ctx).items()
                   if p.get("phase") in facts.AUTHORITATIVE_PHASES and ctx.view.get("Hypothesis", h) is not None)

    def threshold_immutable(ctx):
        eff = facts.effective_hypotheses(ctx)
        return all(eff.get(h, {}).get("phase") == "DRAFT" for p in facts.planned(ctx, "Threshold") if "$key" in p
                   for h in facts.hypotheses_of_threshold(ctx.view, p["$key"]))

    def falsifier_immutable(ctx):
        eff = facts.effective_hypotheses(ctx)
        return all(eff.get(h, {}).get("phase") == "DRAFT" for p in facts.planned(ctx, "Falsifier")
                   for h in facts.inn(ctx.view, "FALSIFIED_BY", "Falsifier", p.get("$key", p.get("id"))))

    def evaluator_immutable(ctx):
        eff = facts.effective_hypotheses(ctx)
        for p in facts.planned(ctx, "Experiment"):
            old = facts.props(ctx.view, "Experiment", p.get("id", p.get("$key")))
            if old is None:
                continue  # a new experiment version: allowed, that is the sanctioned path
            changed = any(k in p and p[k] != old.get(k) for k in ("evaluator_ref", "evidence_schema_ref", "version"))
            if changed and any(eff.get(h, {}).get("phase") != "DRAFT" for h in facts.hypotheses_of_experiment(ctx.view, p["id"])):
                return False
        return True

    def running_has_freeze(ctx):
        return all(not _blank(p.get("freeze_hash")) for p in facts.effective_hypotheses(ctx).values()
                   if p.get("phase") in ("RUNNING", "EVALUATED", "SUPERSEDED"))

    def evaluated_has_evidence_or_reason(ctx):
        rows = verdict_rows(ctx)
        for h, p in facts.effective_hypotheses(ctx).items():
            if p.get("phase") != "EVALUATED" or facts.evidence_count(ctx.view, h) >= 1:
                continue
            if not any(hid == h and v in ("INCONCLUSIVE", "INVALID") and not _blank(reason)
                       for _, v, hid, reason, *_ in rows):
                return False
        return True

    def verdict_machine_derived(ctx):
        for vid, value, h, _reason, dhash, stored in verdict_rows(ctx):
            if h is None or _blank(dhash):
                return False
            if not stored or facts.props(ctx.view, "Hypothesis", h).get("phase") == "EVALUATED":
                if value != ctx.call("derive_verdict", {"hypothesis": h}):
                    return False
        return True

    def verdict_vocab(ctx):
        return all(v in facts.VERDICTS for _, v, *_ in verdict_rows(ctx))

    def evidence_bound(ctx):
        need = ("payload_hash", "git_commit", "experiment_version", "environment")
        if any(_blank(p.get(k)) for p in facts.planned(ctx, "Evidence") for k in need):
            return False
        for r in ctx.view.list("Evidence"):
            owners = facts.inn(ctx.view, "PRODUCES", "Evidence", r["key"])
            if owners and (any(_blank(r["props"].get(k)) for k in need) or any(
                    facts.props(ctx.view, "Experiment", o)["version"] != r["props"]["experiment_version"] for o in owners)):
                return False
        return True

    def orphans_flagged(ctx):
        flagged = {p["$key"] for p in facts.planned(ctx, "Component") if p.get("orphan_flagged") is True and "$key" in p}
        return all(c in flagged or facts.props(ctx.view, "Component", c).get("orphan_flagged") is True
                   for c in facts.active_components_missing(ctx.view))

    def lifecycle_order(ctx):
        now = facts.hypotheses(ctx.view)
        for p in facts.planned(ctx, "Hypothesis"):
            h, new = p.get("$key", p.get("id")), p.get("phase")
            if new is None:
                continue
            if h not in now:
                if new != "DRAFT":
                    return False
            elif new != now[h].get("phase") and not legal_transition(now[h].get("phase"), new):
                return False
        return True

    def rebuild_hash(ctx):  # weak: no Git rebuild exists in the store-only Engine; order-independence of the hash only
        return state_hash(ctx.view) == state_hash(ctx.view, reverse=True)

    def durable_are_git(ctx):
        return all(p["operation"] == "git_change" for p in ctx.planned)

    def no_stale(ctx):
        for p in ctx.planned:
            t, row = p["target"], p["payload"]
            if t not in types:
                continue  # link rows
            if "$key" in row:
                if ctx.view.get(t, row["$key"]) is None:
                    return False
            elif row.get("id") is not None or row.get(types[t]["primary_key"]) is not None:
                key = row.get(types[t]["primary_key"], row.get("id"))
                cur = facts.props(ctx.view, t, key)
                if cur is not None and any(k in cur and cur[k] != v for k, v in row.items() if not k.startswith("$")):
                    return False
        return True

    def conflicts_explicit(ctx):  # weak: only conflicts *within* one action are visible to the Engine
        seen: dict = {}
        for p in ctx.planned:
            key = (p["target"], str(p["payload"].get("$key", p["payload"].get("id"))))
            for f, v in p["payload"].items():
                if not f.startswith("$") and seen.setdefault((key, f), v) != v:
                    return False
        return True

    def ephemeral_marked(ctx):
        for p in ctx.planned:
            fields = fields_of.get((ctx.action, p["index"]))
            allowed = {"$key", "$hypothesis", "$src", "$dst"} | set(fields or ())
            if fields is None and p["target"] in types:  # object effect with no declared fields: any declared property
                allowed |= set(pr["name"] for pr in types[p["target"]]["properties"])
            if set(p["payload"]) - allowed:
                return False
        return True

    def history_preserved(ctx):
        for p in ctx.planned:
            t, row = p["target"], p["payload"]
            if t not in types:
                continue
            key = row.get("$key", row.get(types[t]["primary_key"], row.get("id")))
            cur = facts.props(ctx.view, t, key)
            if cur is None:
                continue
            for pr in types[t]["properties"]:
                n = pr["name"]
                if pr.get("immutable") and n in row and n in cur and row[n] != cur[n]:
                    return False
        return True

    return {
        "constraint:supported-needs-evidence:v1": supported_needs_evidence,
        "constraint:preregistration-complete-contract:v1": prereg_complete,
        "constraint:threshold-immutable-after-preregistration:v1": threshold_immutable,
        "constraint:falsifier-immutable-after-preregistration:v1": falsifier_immutable,
        "constraint:evaluator-immutable-after-preregistration:v1": evaluator_immutable,
        "constraint:running-requires-freeze-hash:v1": running_has_freeze,
        "constraint:evaluated-requires-evidence-or-reason:v1": evaluated_has_evidence_or_reason,
        "constraint:verdict-machine-derived:v1": verdict_machine_derived,
        "enum:SUPPORTED|REJECTED|INCONCLUSIVE|INVALID on value": verdict_vocab,
        "constraint:evidence-bound-to-version-commit-environment:v1": evidence_bound,
        "constraint:orphan-component-flagged-not-deleted:v1": orphans_flagged,
        "constraint:lifecycle-order:v1": lifecycle_order,
        "constraint:rebuild-reproduces-state-hash:v1": rebuild_hash,
        "constraint:durable-actions-are-git-changes:v1": durable_are_git,
        "constraint:no-silent-stale-write:v1": no_stale,
        "constraint:conflicts-surface-explicitly:v1": conflicts_explicit,
        "constraint:ephemeral-state-marked:v1": ephemeral_marked,
        "constraint:historical-binding-preserved:v1": history_preserved,
    }
