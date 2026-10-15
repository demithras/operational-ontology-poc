"""Private service sets (anchor with control plane, ExternalWorld, AuthorityService) started by a PYTHON caller (tests, the mutation proof).
scripts/run_h29.sh starts the same layout from bash for real runs: <root>/anchor-i, ext-i, auth-i (+ .sock) and <root>/systems.json."""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from r3_shared.anchor import start_anchor
from r3_shared.authsvc import start_authority
from r3_shared.extworld import start_external

from r3_harness.h28 import specs as s28


class SvcSet:
    def __init__(self, n: int = 1, root: str | Path | None = None):
        self.root = Path(root) if root else Path(tempfile.mkdtemp(prefix="h29s"))
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "systems.json").write_text(json.dumps(s28.combined_systems()))
        self.procs, self.closed = [], None
        try:
            for i in range(n):
                a = start_anchor(self.root / f"anchor-{i}", self.root / f"anchor-{i}.sock", control=True)
                e = start_external(self.root / f"ext-{i}", self.root / "systems.json", self.root / f"ext-{i}.sock")
                u = start_authority(self.root / f"auth-{i}", self.root / f"auth-{i}.sock")
                self.procs.append((a, e, u))
        except Exception:
            self.close()
            raise

    def close(self) -> dict:
        """Close every service (keys revealed); idempotent. -> {"anchor": [...], "ext": [...], "auth": [...]} close() outputs."""
        if self.closed is None:
            out = {"anchor": [], "ext": [], "auth": []}
            for a, e, u in self.procs:
                for key, p in (("anchor", a), ("ext", e), ("auth", u)):
                    try:
                        out[key].append(p.close())
                    except Exception as exc:  # noqa: BLE001
                        out[key].append({"error": str(exc)})
                        try:
                            p.proc.kill()
                        except Exception:  # noqa: BLE001
                            pass
            self.closed = out
        return self.closed

    def cleanup(self) -> None:
        self.close()
        shutil.rmtree(self.root, ignore_errors=True)
