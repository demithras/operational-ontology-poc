"""CaseBook: the in-memory fold of the committed `governance` marks (+ journal records). It is a CACHE: it is rebuilt from
the world_log on restart and extended only from rows that are already committed, so a rolled-back transaction can
never leave a trace in it (R25-7)."""
from __future__ import annotations

from .govproc import Case, Judgment


class CaseBook:
    def __init__(self):
        self.cases: dict[str, Case] = {}
        self.ends: dict[str, tuple[int, int, str]] = {}  # emergency id -> (seq, tick, by)
        self.by_rid: dict[str, dict] = {}  # request_id -> {"seq","fp","status","body"} (constitutional idempotency)
        self.gov_versions: list[tuple[int, str]] = []  # (seq, document digest) of every set_governance
        self.last_seq = 0

    def refold(self, h, journal) -> None:
        """Apply every committed governance mark with seq > last_seq (commit order)."""
        rows = h._con.execute("SELECT seq, tick, data_json FROM world_log WHERE kind='mark' AND ref='governance' "
                              "AND seq>? ORDER BY seq", (self.last_seq,)).fetchall()
        import json
        for seq, tick, raw in rows:
            m, rec = json.loads(raw), journal.get(h, seq)
            op = m["op"]
            if op == "propose":
                self.cases[m["case"]] = Case(m["case"], m["requester"], m["on_behalf_of"], m["operation"],
                                             rec["args"], seq, tick)
            elif op == "judge":
                self.cases[m["case"]].judgments.append(
                    Judgment(seq, tick, m["stage"], m["judge"], m["value"], rec["rid"]))
            elif op == "appeal":
                self.cases[m["case"]].appeal = (seq, tick, m["by"])
            elif op == "execute":
                self.cases[m["case"]].executed = {"status": rec["status"], "body": rec["body"]}
            elif op == "end":
                self.ends.setdefault(m["emergency"], (seq, tick, rec["by"]))
            elif op == "set_governance":
                self.gov_versions.append((seq, m["version"]))
            if rec.get("rid"):
                self.by_rid[rec["rid"]] = {"seq": seq, "fp": rec["fp"], "status": rec["status"], "body": rec["body"]}
            self.last_seq = seq
