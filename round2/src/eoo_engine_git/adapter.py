"""``git_change`` adapter over a GitStore (Engine adapter interface: apply / observations; ENGINE_PREREG H20).

Allowed: translate an approved effect into a Git change, return the raw response, emit observations.
Not here: authority, policy, preconditions, idempotency decisions, lifecycle state (the Engine owns those).

One governed Action = one commit. The Engine hands an adapter one effect at a time, but it builds every payload of an
action before the first adapter call, through the ``payload`` bindings. ``attach`` wraps those bindings so the adapter
learns the full batch first; the first ``apply`` of an execution then commits all of its effects at once and every
effect's response names that one commit. If the batch is not complete the adapter refuses (BatchError): it never
falls back to one commit per effect.

Provenance (Engine v1.2): the commit message is ``effect["envelope_text"]`` of the effect whose ``apply`` triggers the
commit, written verbatim (its execution-effects field lists the whole batch). The adapter composes no provenance; the
facts of the write (commit, parent = head at write, base, merge mode, state digest, writer, batch) go back in the
response, and the Engine records them.
"""
from __future__ import annotations

from typing import Any, Iterable

from eoo_engine import LogicBindings
from eoo_engine.canon import to_plain
from eoo_engine.effects import build_payload
from eoo_engine.registry import load_model

from .errors import BatchError
from .store import MAIN, GitStore


class GitAdapter:
    def __init__(self, store: GitStore, writer: str, base: str | None = None, ref: str = MAIN, merge_mode: str = "compatible"):
        self.store, self.writer, self.ref, self.merge_mode = store, writer, ref, merge_mode
        self.base = base or store.head(ref)  # the commit the writer's Engine projection was built from; never advances
        self._board: dict[str, dict[int, tuple[str, dict]]] = {}
        self._responses: dict[str, dict] = {}
        self._commits: list[dict] = []
        self.observe = True

    # ---- called by the wrapped payload bindings ------------------------------------------
    def note(self, execution: str, index: int, target: str, payload: dict) -> None:
        self._board.setdefault(execution, {})[index] = (target, to_plain(payload))

    # ---- Engine adapter interface ---------------------------------------------------------
    def apply(self, effect: Any, payload: Any) -> dict:
        eid, ex = effect["effect_id"], effect["execution"]
        idx = int(eid.rsplit("/e", 1)[1])
        pay = to_plain(payload)
        prior = self._responses.get(eid)
        if prior is not None and prior["row"] == pay and prior["target"] == effect["target"]:
            return dict(prior)  # content-addressed: the same change is never written twice
        batch, want = self._board.get(ex, {}), self.store.n_git.get(effect["action"])
        if want is None or len(batch) != want or idx not in batch or batch[idx][1] != pay:
            raise BatchError(f"{eid}: payloads announced {sorted(batch)} of {want} effects; refusing a partial commit")
        rows = [batch[i] for i in sorted(batch)]
        effects = [f"{ex}/e{i}" for i in sorted(batch)]
        rec = self.store.commit_rows(rows=rows, base=self.base, writer=self.writer, merge_mode=self.merge_mode, ref=self.ref,
                                     meta={"execution": ex, "action": effect["action"], "effects": effects},
                                     message=effect.get("envelope_text"))
        self._commits.append({**rec, "committed_at": self.store.clock()})
        for i in sorted(batch):
            self._responses[f"{ex}/e{i}"] = {"commit": rec["sha"], "parent": rec["parent"], "target": batch[i][0],
                                             "row": batch[i][1], "base": rec["base"], "head_at_write": rec["head_at_write"],
                                             "merge": rec["merge"], "state_hash": rec["state_hash"], "writer": rec["writer"],
                                             "batch": effects}
        del self._board[ex]
        return dict(self._responses[eid])

    def observations(self) -> Iterable[dict]:
        if not self.observe or self.store.obs_type is None:
            return []
        return [{"observation_type": self.store.obs_type, "execution": c["execution"],
                 "data": {"sha": c["sha"], "committed_at": c["committed_at"]}} for c in self._commits]


def attach(bindings, package: dict, adapter: GitAdapter):
    """Wrap every ``payload`` of a ``git_change`` effect so the adapter is told the batch. Returns the bindings.

    An effect whose payload the Engine derives from the action inputs (no binding) gets a wrapper that derives the same
    payload through the Engine's own ``effects.build_payload`` over an empty binding set.
    """
    model = load_model(package)
    for act in package["actions"]:
        spec = model.get("actions", act["id"])
        for i, eff in enumerate(act["effects"]):
            if eff["operation"] != "git_change":
                continue
            key = f"{act['id']}#{i}"
            orig = bindings.get("payload", key) if bindings.has("payload", key) else None

            def wrapped(ctx, _orig=orig, _spec=spec, _eff=spec.effects[i], _i=i, _t=eff["target"]):
                out = _orig(ctx) if _orig else build_payload(_spec, _eff, ctx.inputs, ctx, LogicBindings())
                adapter.note(ctx.execution, _i, _t, out)
                return out
            bindings.bind("payload", key, wrapped)
    return bindings
