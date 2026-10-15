"""Shared helpers for the P1f tests (r3_shared only)."""
import json
import os
import sqlite3
import tempfile

from r3_shared import extcap
from r3_shared.extadapter import payload_digest
from r3_shared.extsystems import load_systems
from r3_shared.extworld_core import ExternalWorldCore

KEY = bytes(range(32))
PAY = {"po_id": "PO-1", "expedite_fee": 10}
TARGET = "po:PO-1"


def core(domain="manufacturing", d=None):
    return ExternalWorldCore(d or tempfile.mkdtemp(prefix="r3x"), load_systems(domain), root_key=KEY)


def cap_for(c, system="ERP", operation="expedite", target=TARGET, payload=None, correlation="r1#0", max_uses=1, not_after=9,
            dep="dep1"):
    """A correctly scoped per-effect cap (R28-13)."""
    root = c.issue_root(dep, system)
    return extcap.attenuate(root, system=system, operation=operation, target=target,
                            payload_digest=payload_digest(PAY if payload is None else payload), correlation=correlation,
                            max_uses=max_uses, not_after_tick=not_after)


def audit(c):
    c.con.row_factory = sqlite3.Row
    rows = [dict(r) for r in c.con.execute("SELECT * FROM audit ORDER BY seq")]
    c.con.row_factory = None
    return rows


def eff_count(c):
    return c.con.execute("SELECT count(*) FROM effects").fetchone()[0]
