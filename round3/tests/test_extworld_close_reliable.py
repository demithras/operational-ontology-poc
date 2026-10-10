"""ExternalWorld close must deliver its reply (revealed root key + head) before the server process exits, even on a busy host."""
import json
import os
import tempfile
from pathlib import Path

from r3_shared.extsystems import load_systems
from r3_shared.extworld import start_external


def test_close_reply_is_always_delivered_with_key():
    sp = Path(tempfile.mkdtemp(prefix="ecs")) / "sys.json"
    sp.write_text(json.dumps(load_systems("manufacturing")))
    for i in range(40):
        d = Path(tempfile.mkdtemp(prefix="ecr"))
        p = start_external(d / "ext", sp, os.path.join(tempfile.mkdtemp(prefix="r3s"), "s"))
        c = p.client()
        c.advance(1)
        assert c.tick() == 1, i
        r = p.close()
        assert len(r["root_key_hex"]) == 64 and r["head"] is not None, i
        assert p.proc.returncode == 0, i
