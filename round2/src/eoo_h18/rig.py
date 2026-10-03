"""EooRig: the Project Ontology on the unchanged Engine over a real (temporary) Git repository."""
from __future__ import annotations

import copy
import datetime as dt
import tempfile
from pathlib import Path

from domains._pack import boot, load_ir
from domains.project.pack import build_pack
from domains.project.seed_from_repo import build_seed
from eoo_engine import ENGINE_VERSION, parse_envelope
from eoo_engine.provenance import LABELS
from eoo_engine_git import GitStore
from eoo_exp.util import load_oracle

from .evaluators import registry
from .fixture import case_ops
from .gen import classify
from .ops import engine_call
from .summary import summarize

W = load_oracle("h18", "world")
T0 = dt.datetime(2026, 10, 2, tzinfo=dt.timezone.utc)
PRINCIPAL = "researcher-1"


def trailers(msg: str) -> dict:
    """Engine v1.2: the commit message IS the Engine's provenance envelope; {label: value} of its parsed fields."""
    return {LABELS[f]: v for f, v in parse_envelope(msg).items()}


class EooRig:
    def __init__(self, workdir=None, *, reader, mutate=None, provenance=True, merge_mode="compatible", h15_state="EVALUATED",
                 package=None, extend=None, extra_ops=()):
        self.workdir = Path(workdir or tempfile.mkdtemp(prefix="eoo-h18-"))
        self.reader, self.mutate, self.merge_mode = reader, mutate, merge_mode
        self.package, self.extend = package or load_ir("project"), extend
        self.seed = build_seed(reader, h15_state=h15_state)
        self.base_ops, self.commit0 = self.seed["ops"] + list(extra_ops), self.seed["head_commit"]
        self.tick = 0
        self.store = GitStore.init(self.workdir / "repo", self.package, engine_version=ENGINE_VERSION, clock=self._clock)
        if not provenance:  # H18 mutant M3 (ablation, harness-side): the envelope never reaches the commit message
            commit_rows = self.store.commit_rows
            self.store.commit_rows = lambda **kw: commit_rows(**{**kw, "message": "detached\n"})
        self.root = self.store.import_ops(self.base_ops, source=f"real-repo@{self.commit0}")
        self.evaluators = registry(reader)

    def _clock(self) -> str:
        self.tick += 1
        return (T0 + dt.timedelta(seconds=self.tick)).isoformat()

    def engine(self, ref: str, writer: str = "w1", base: str | None = None):
        pack = build_pack(store=self.store, base=base, ref=ref, writer=writer, evaluators=self.evaluators, reader=self.reader,
                          mutate=self.mutate, merge_mode=self.merge_mode, ir=self.package, extend=self.extend)
        return boot("project", pack, clock=lambda: T0.isoformat(), package=self.package)

    def open_case(self, case: dict, label: str) -> str:
        ref = f"refs/heads/case-{label}"
        self.last_start = self.store.import_ops(case_ops(self.base_ops, case), source=f"case:{label}", ref=ref, parent=self.root)
        return ref

    def step(self, case: dict, ref: str, i: int, op: dict) -> dict:
        """Run one op through a fresh Engine projected from the case branch head; returns the observation row."""
        st = self.store
        head0 = st.head(ref)
        exp_ids = [k for (t, k) in st.state_at(head0).objects if t == "Experiment"]
        action, inputs = engine_call(case, op, exp_ids)
        e = self.engine(ref)
        h0, n0 = e.state().state_hash(), len(st.history(head0))
        row = {"i": i, "op": op["k"], "action": action, "exception": None}
        try:
            rec = e.propose(action, inputs, PRINCIPAL, idempotency_key=f"{ref[-12:]}-{i}")
        except Exception as ex:  # noqa: BLE001 - recorded: a harness/engine crash is a failure row, never a silent pass
            row.update(exception=f"{type(ex).__name__}: {str(ex)[:160]}", state="EXCEPTION", accepted=False, denied_gate=None)
            rec = None
        head1 = st.head(ref)
        if rec is not None:
            gates = [g["gate"] for g in rec["gates"] if not g["passed"]]
            row.update(state=rec["state"], accepted=rec["state"] == "RECONCILED_SUCCESS", denied_gate=gates[0] if gates else None,
                       adapter_errors=[a["error"][:120] for a in rec.get("adapter_errors", [])])
        row["new_commits"] = len(st.history(head1)) - n0
        row["committed"] = row["new_commits"] > 0
        row["engine_store_unchanged"] = e.state().state_hash() == h0
        row["effects_all_git"] = all(x["operation"] == "git_change" for x in e.effect_log.entries())
        if row["accepted"]:
            msg = st.repo.read_commit(head1)["message"]
            tr = trailers(msg)
            resp = {r["commit"] for r in rec["responses"].values()}
            row["trace"] = {"execution": tr.get("EOO-Execution") == rec["exec"], "action": tr.get("EOO-Action") == action,
                            "base": bool(rec["responses"]) and all(r.get("base") == head0 for r in rec["responses"].values()),
                            "engine_version": tr.get("EOO-Engine-Version") == ENGINE_VERSION,
                            "responses_name_the_commit": resp == {head1},
                            "observed": any(o["observation"]["data"]["sha"] == head1 for o in rec["observations"])}
        row["summary"] = summarize(st.files_at(head1), case["subject"], case)
        return row

    def run_case(self, case: dict, label: str) -> list:
        ref = self.open_case(case, label)
        w, rows = W.World(copy.deepcopy(case)), []
        for i, op in enumerate(case["ops"]):
            pre = copy.deepcopy(w)
            legal, want = w.step(op)
            row = self.step(case, ref, i, op)
            row["oracle_legal"], row["classes"] = legal, classify(pre, op, legal)
            if legal and not row["accepted"]:  # a legal op the Engine refused: recorded; the oracle resyncs to the Engine
                row["divergence"], w, want = "legal_rejected", pre, pre.summary()
            elif not legal and (row["accepted"] or row["committed"]):  # an illegal op that reached Git: recorded; the case stops here
                row["divergence"] = "illegal_accepted"
            row["summary_match"] = row["summary"] == want
            if not row["summary_match"]:
                row["summary_diff"] = sorted(k for k in want if want[k] != row["summary"][k])
            rows.append(row)
            if row.get("divergence") == "illegal_accepted":
                break
        return rows
