"""Harness-side handles on the three launcher-started services (anchor, ExternalWorld, AuthorityService), the OBS symlink gate, the
tamper primitives, byte copies of durable stores, and the one absolute clock (G4-E26: the host, the anchor, ExternalWorld and the
AuthorityService all advance in the same step). No oracle logic here."""
from __future__ import annotations

import importlib
import os
import shutil
from pathlib import Path

from r3_shared.anchor import AnchorClient, AnchorControl
from r3_shared.authsvc import AuthorityControl
from r3_shared.extworld import ExternalClient
from r3_shared.histstore import HistoryStore, TamperView

from . import rules


class Services:
    """One worker's service set. Sockets come from the launcher environment (R3_ANCHOR_*, R3_EXT_*, R3_AUTH_*)."""

    def __init__(self, anchor_sock, ext_sock, ext_ctl, ext_dir, auth_sock, auth_ctl, anchor_dir=None, auth_dir=None):
        self.anchor_sock, self.ext_sock, self.ext_dir, self.auth_sock = anchor_sock, ext_sock, str(ext_dir), auth_sock
        self.anchor_dir, self.auth_dir = anchor_dir, auth_dir
        self.anchor = AnchorClient(anchor_sock)
        self.anchor_ctl = AnchorControl(str(anchor_sock) + ".ctl")
        self.ext = ExternalClient(ext_sock, ext_ctl)
        self.auth = AuthorityControl(auth_ctl)
        self.auth_sock_path = auth_sock

    @classmethod
    def from_env(cls, env=None):
        e = os.environ if env is None else env
        return cls(e["R3_ANCHOR_SOCK"], e["R3_EXT_SOCK"], e["R3_EXT_CTL"], e["R3_EXT_DIR"], e["R3_AUTH_SOCK"], e["R3_AUTH_CTL"],
                   e.get("R3_ANCHOR_DIR"), e.get("R3_AUTH_DIR"))

    def advance_all(self, tick: int) -> None:
        self.anchor_ctl.advance(tick)
        self.ext.advance(tick)
        self.auth.advance(tick)

    def now(self) -> int:
        return max(self.anchor_ctl.tick(), self.ext.tick(), self.auth.tick())


def audience_of(variant_name: str) -> str:
    """The token audience of a variant: class attribute `audience`, read through the registry (real variants) or module:Class (fakes)."""
    if ":" in variant_name:
        mod, cls = variant_name.split(":")
        return getattr(getattr(importlib.import_module(mod), cls), "audience", None) or "fake"
    from r3_shared.registry import load_variant
    return getattr(type(load_variant(variant_name)), "audience", None) or "fake"


def layout_of(variant_name: str) -> dict:
    """HISTORY_LAYOUT (class attribute) of the variant, {} when absent. Used only to pick tamper targets (P1d-5: no obscurity credit)."""
    try:
        if ":" in variant_name:
            mod, cls = variant_name.split(":")
            return dict(getattr(getattr(importlib.import_module(mod), cls), "HISTORY_LAYOUT", {}) or {})
        from r3_shared.registry import load_variant
        v = load_variant(variant_name)
        return dict(getattr(type(v), "HISTORY_LAYOUT", None) or getattr(v, "HISTORY_LAYOUT", {}) or {})
    except Exception:  # noqa: BLE001
        return {}


# ---- OBS gate: the observer opens <obs_dir>/external.db; the harness removes / restores the symlink (client-side outage) --------
def obs_dir(root: Path, tag: str, ext_dir: str) -> Path:
    d = Path(root) / f"obs-{tag}"
    d.mkdir(parents=True, exist_ok=True)
    link = d / "external.db"
    if not link.exists() and not link.is_symlink():
        link.symlink_to(Path(ext_dir) / "external.db")
    return d


def obs_set(d: Path, ext_dir: str, up: bool) -> None:
    link = Path(d) / "external.db"
    if up:
        if not link.is_symlink() and not link.exists():
            link.symlink_to(Path(ext_dir) / "external.db")
    elif link.is_symlink():
        link.unlink()


# ---- durable stores: byte copies (RC1) and tamper (F8 / B4) ----------------------------------------------------------------
def copy_store(src_dir: Path, dst_dir: Path) -> list:
    """Byte-identical copies of every durable file (world.db, hist.db, with -wal/-shm); the host must be dead."""
    dst_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for p in sorted(Path(src_dir).glob("*.db*")):
        shutil.copyfile(p, dst_dir / p.name)
        out.append(p.name)
    fs = Path(src_dir) / "fakestate"                      # tests only: the reference fakes keep extra durable files in this directory
    if fs.is_dir():
        shutil.copytree(fs, dst_dir / "fakestate")
        out.append("fakestate/")
    return out


def tamper(what: str, hist_path: str, world_path: str, layout: dict) -> dict:
    """Apply one tamper to the dead host's stores. -> record {what, keys, applied}. Kinds are content-agnostic primitives over the
    variant's declared record classes (HISTORY_LAYOUT) applied through TamperView only; delete_store (B4) removes world + history."""
    if what not in rules.TAMPER_KINDS + rules.BOUNDARY_TAMPER:
        raise ValueError(f"unknown tamper {what!r}")
    if what == "delete_store":
        n = 0
        for base in (hist_path, world_path):
            for p in Path(base).parent.glob(Path(base).name + "*"):
                p.unlink()
                n += 1
        return {"what": what, "keys": [], "applied": n > 0}
    tv = TamperView(hist_path)
    try:
        pref = {"forge_approval": layout.get("approval", "led/appr/"), "delete_idempotency": layout.get("idempotency", "led/req/"),
                "rewrite_meta": layout.get("ledger_meta") or layout.get("meta", "led/meta/")}[what]
        keys = [k for k in tv.keys(pref) if k != "meta/stream"]
        if what == "forge_approval":
            if keys:
                tv.write(keys[0] + "~forged", tv.read(keys[0]) or b"")
            return {"what": what, "keys": keys[:1], "applied": bool(keys)}
        if what == "delete_idempotency":
            for k in keys:
                tv.delete(k)
            return {"what": what, "keys": keys, "applied": bool(keys)}
        if keys:
            raw = tv.read(keys[0]) or b""
            tv.write(keys[0], raw[:-1] + bytes([(raw[-1] ^ 1) if raw else 1]))
        return {"what": what, "keys": keys[:1], "applied": bool(keys)}
    finally:
        tv.close()


def stream_of(hist_path: str) -> str | None:
    """The anchor stream id of the deployment, read from the frozen record `meta/stream` (needed to key an anchor partition, G5-E6)."""
    try:
        h = HistoryStore(hist_path)
        try:
            raw = h.get("meta/stream")
        finally:
            h.close()
        return raw.decode() if raw else None
    except Exception:  # noqa: BLE001
        return None
