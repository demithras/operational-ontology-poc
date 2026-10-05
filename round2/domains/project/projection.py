"""Rebuild the ontology projection from Git (docs/05: Git is canonical, the ontology is a rebuildable projection).

``git_change`` effects go to the Git adapter, never into the Engine store. To continue a lifecycle after a governed
change, boot a new Engine from ``project(seed, git)``: the seed with every Git commit replayed over it. Replay is
mechanical (no policy, no authority): a row with ``$key`` updates, a row with ``$src/$dst`` links, any other row creates
(or overwrites the row with the same key).
"""
from __future__ import annotations

import copy

from .adapters.git_fake import GitFake



def project(seed: dict, git: GitFake) -> dict:
    out = copy.deepcopy(seed)
    ops = out["ops"]
    idx = {(o["type"], o["key"]): o for o in ops if o["op"] == "create"}
    for c in git.commits:
        target, row = c["target"], dict(c["row"])
        if "$src" in row:
            end = {"EVALUATES": ("Verdict", "Hypothesis"), "PRODUCES": ("Experiment", "Evidence"),
                   "SUPERSEDED_BY": ("Hypothesis", "Hypothesis"), "CHANGES": ("Decision", "ContractVersion"), "SUPPORTS_OR_REFUTES": ("Evidence", "Hypothesis"),
                   "NEW_VERSION_OF": ("Experiment", "Experiment")}[target]
            if any(o["op"] == "link" and o["type"] == target and o["src"] == [end[0], row["$src"]]
                   and o["dst"] == [end[1], row["$dst"]] for o in ops):
                continue  # already projected (seed pre-declares it, or a replayed commit)
            ops.append({"op": "link", "type": target, "src": [end[0], row["$src"]], "dst": [end[1], row["$dst"]],
                        "props": {}})
            continue
        key = row.pop("$key", None)
        row.pop("$hypothesis", None)
        if key is not None:
            idx[(target, key)]["props"].update(row)
        elif (target, row["id"]) in idx:
            idx[(target, row["id"])]["props"].update(row)
        else:
            op = {"op": "create", "type": target, "key": row["id"], "props": row}
            ops.insert(_first_link(ops), op)
            idx[(target, row["id"])] = op
    return out


def _first_link(ops: list) -> int:
    return next((i for i, o in enumerate(ops) if o["op"] == "link"), len(ops))
