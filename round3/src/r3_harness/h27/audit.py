"""Anchor audit E1-E5 (PROT-H27 s4). E1/E3/E4 are probed from INSIDE the harness process at run time; E2/E5 are finalised
after the anchor closed (scripts/run_h27.py --finalize). Probes never corrupt the log (no bytes are appended)."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from r3_shared.anchor import KEY_NAME, AnchorClient, verify_anchor_log


def _try(fn) -> str:
    try:
        fn()
        return "ok"
    except PermissionError:
        return "PermissionError"
    except OSError as exc:
        return type(exc).__name__


def probe(anchor_dir: str, sock: str) -> dict:
    d = Path(anchor_dir)
    created = d / f".probe-{os.getpid()}"
    mode = stat.S_IMODE(d.stat().st_mode) if d.exists() else 0
    res = {
        "open_log_for_write": _try(lambda: open(d / "anchor.log", "ab").close()),
        "create_file": _try(lambda: created.write_bytes(b"x")),
        "chmod_dir": _try(lambda: os.chmod(d, mode)),
        "mkdir": _try(lambda: os.mkdir(d / f".probe-dir-{os.getpid()}")),
    }
    for p in (created, d / f".probe-dir-{os.getpid()}"):
        try:
            p.unlink() if p.is_file() else p.rmdir()
        except OSError:
            pass
    pid = None
    try:
        pid = AnchorClient(sock)._call({"op": "ping"})["pid"]
    except Exception:  # noqa: BLE001
        pass
    e4 = all(v == "PermissionError" for v in res.values())
    writable_bits = bool(mode & stat.S_IWUSR)
    level = "none" if not e4 else ("sandbox-exec" if writable_bits else "chmod")
    return {"harness_pid": os.getpid(), "anchor_pid": pid, "E1_separate_process": pid is not None and pid != os.getpid(),
            "E4_probe": res, "E4_all_denied": e4, "E3_enforcement": level,
            "E3_holds": e4 and level in ("sandbox-exec", "chmod"), "key_revealed_during_run": (d / KEY_NAME).exists()}


def safe_verify(anchor_dir, expected_head=None) -> dict:
    """verify_anchor_log, but a log it cannot even parse structurally (it raises) is an E5 FAILURE, not a harness crash."""
    try:
        return verify_anchor_log(anchor_dir, expected_head=expected_head)
    except Exception as exc:  # noqa: BLE001 - r3_shared reports shape errors by raising; see report (frozen module)
        return {"ok": False, "chain_ok": False, "mac_ok": False, "head_ok": False, "entries": None,
                "errors": [f"verify_anchor_log raised {type(exc).__name__}: {exc}"]}


def finalize(audit: dict, anchor_copy: str, closed_head: dict | None) -> dict:
    """E2 (key revealed only at close, MACs verify) and E5 (chain + MAC + head equals the head reported at close)."""
    v = safe_verify(anchor_copy, closed_head)
    out = dict(audit)
    out["E2_key_only_at_close"] = (not audit.get("key_revealed_during_run", True)) and v["mac_ok"]
    out["E5_log_integrity"] = bool(v["ok"]) and closed_head is not None
    out["E5_detail"] = {k: v[k] for k in ("ok", "chain_ok", "mac_ok", "head_ok", "entries", "errors")}
    out["closed_head"] = closed_head
    out["finalized"] = True
    return out


def load(path: Path) -> dict:
    return json.loads(path.read_text())
