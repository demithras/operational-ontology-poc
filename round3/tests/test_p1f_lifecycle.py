"""ExternalWorld lifecycle: start -> write -> observe -> close end to end; the H28 runner guard (G3-E31b: a non-dev id refuses to run
without the service); the sandbox profile denies harness-process writes to <ext_dir> while the socket and read-only observation
still work (known-negative + known-positive); the session hygiene in tests/conftest.py also covers the new process."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from r3_shared import extcap
from r3_shared.extadapter import payload_digest
from r3_shared.extobs import ObservationClient
from r3_shared.extsystems import load_systems
from r3_shared.extworld import ExternalError, is_dev_id, require_external, start_external

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
PAY = {"po_id": "PO-1", "expedite_fee": 10}


def _start(tmp_path):
    sp = tmp_path / "systems.json"
    sp.write_text(json.dumps(load_systems("manufacturing")))
    return start_external(tmp_path / "ext", sp, os.path.join(tempfile.mkdtemp(prefix="r3sock"), "s"))


def test_start_write_observe_close_end_to_end(tmp_path):
    p = _start(tmp_path)
    c = p.client()
    assert c.ping()["plane"] == "data" and c.tick() == 0
    c.advance(1)
    cap = extcap.attenuate(c.issue_root("dep", "ERP"), operation="expedite", target="po:PO-1", payload_digest=payload_digest(PAY),
                           correlation="r#0", max_uses=1, not_after_tick=9)
    assert c.data_only().write(cap, "expedite", "po:PO-1", PAY, "adp").status == "applied"
    obs = ObservationClient(p.ext_dir, c.observer_key("dep"), load_systems("manufacturing"))
    snap = obs.read(1)
    assert [r.correlation for r in snap.effects] == ["r#0"]
    out = p.close()
    assert p.proc.poll() is not None, "server process must exit after close()"
    assert out["head"] == {"effects": 1, "audit": 1}
    assert (Path(p.ext_dir) / "HEAD.final").exists() and (Path(p.ext_dir) / "KEY.revealed").read_text() == out["root_key_hex"]
    assert [r.correlation for r in obs.read(5).effects] == ["r#0"]          # a closed ledger stays readable read-only
    with pytest.raises(ExternalError):
        c.ping()


def test_existing_ledger_dir_is_refused(tmp_path):
    p = _start(tmp_path)
    p.close()
    with pytest.raises(ExternalError, match="already holds a ledger"):
        start_external(tmp_path / "ext", tmp_path / "systems.json", tmp_path / "s2")


def test_runner_guard_refuses_non_dev_id_without_running_service(tmp_path):
    assert is_dev_id("exp-h28-dev1") and is_dev_id("exp-h28-smoke-dev-1") and not is_dev_id("exp-h28-001")
    with pytest.raises(ExternalError, match="requires R3_EXT_SOCK"):
        require_external("exp-h28-001", env={})
    with pytest.raises(ExternalError, match="no ExternalWorld configured"):
        require_external("exp-h28-dev1", env={})
    p = _start(tmp_path)
    env = {"R3_EXT_SOCK": p.sock_path, "R3_EXT_CTL": p.ctl_path, "R3_EXT_DIR": p.ext_dir}
    assert require_external("exp-h28-001", env=env) == (p.sock_path, p.ctl_path, p.ext_dir)
    p.close()
    with pytest.raises(ExternalError, match="is not running"):             # variables set but the service is gone
        require_external("exp-h28-001", env=env)
    with pytest.raises(ExternalError, match="requires R3_EXT_SOCK"):
        require_external("exp-h28-001", env={"R3_EXT_SOCK": p.sock_path})


CHILD = r'''
import json, os, sys
from r3_shared.extobs import ObservationClient
from r3_shared.extworld import ExternalClient, ExternalError
d, sock, key, cap = sys.argv[1:5]
out = {}
def attempt(name, fn):
    try:
        fn(); out[name] = "ok"
    except PermissionError: out[name] = "PermissionError"
    except Exception as e: out[name] = type(e).__name__
attempt("create_in_ext_dir", lambda: open(os.path.join(d, "evil"), "w").write("x"))
attempt("append_ledger", lambda: open(os.path.join(d, "external.db"), "ab").write(b"x"))
attempt("unlink_ledger", lambda: os.unlink(os.path.join(d, "external.db")))
attempt("write_elsewhere", lambda: open(os.path.join(os.path.dirname(d), "fine"), "w").write("x"))
c = ExternalClient(sock)
attempt("socket_write", lambda: c.write(cap, "expedite", "po:PO-1", json.loads(sys.argv[5]), "adp"))
sysd = json.load(open(sys.argv[6]))
attempt("observe_readonly", lambda: len(ObservationClient(d, key, sysd).read(3).effects) == 1 or 1 / 0)
print(json.dumps(out))
'''


def test_sandbox_denies_ext_dir_writes_but_socket_and_observer_work(tmp_path):
    assert shutil.which("sandbox-exec"), "sandbox-exec unavailable: the ExternalWorld write-denial cannot be enforced - report to the author"
    p = _start(tmp_path)
    c = p.client()
    c.advance(1)
    cap = extcap.attenuate(c.issue_root("dep", "ERP"), operation="expedite", target="po:PO-1", payload_digest=payload_digest(PAY),
                           correlation="r#0", max_uses=1, not_after_tick=9)
    key = c.observer_key("dep")
    ext = os.path.realpath(p.ext_dir)
    profile = f'(version 1)(allow default)(deny file-write* (subpath "{ext}"))'
    sysp = tmp_path / "systems.json"
    r = subprocess.run(["sandbox-exec", "-p", profile, sys.executable, "-c", CHILD, ext, p.sock_path, key, cap, json.dumps(PAY), str(sysp)],
                       capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(SRC)}, timeout=120)
    out = p.close()
    assert r.returncode == 0, r.stderr
    res = json.loads(r.stdout.strip().splitlines()[-1])
    for k in ("create_in_ext_dir", "append_ledger", "unlink_ledger"):
        assert res[k] == "PermissionError", (k, res)                         # known negatives
    assert res["write_elsewhere"] == "ok"                                      # known positive
    assert res["socket_write"] == "ok" and res["observe_readonly"] == "ok"    # the ONLY write path is the service; reads work
    assert out["head"]["effects"] == 1 and not (Path(ext) / "evil").exists()


LEAKY = '''
import json, os, tempfile
from r3_shared.extsystems import load_systems
from r3_shared.extworld import start_external
def test_leaks():
    d = tempfile.mkdtemp()
    sp = os.path.join(d, "s.json")
    open(sp, "w").write(json.dumps(load_systems("manufacturing")))
    start_external(os.path.join(d, "ext"), sp, os.path.join(d, "s"))     # never closed
'''


def _session(tmp: Path, body: str, name: str):
    shutil.copy(HERE / "conftest.py", tmp / "conftest.py")
    (tmp / name).write_text(body)
    env = {**os.environ, "PYTHONPATH": str(SRC), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(tmp / name)],
                          capture_output=True, text=True, env=env, cwd=str(tmp))


def test_session_hygiene_catches_a_leaked_external_world(tmp_path):
    r = _session(tmp_path, LEAKY, "test_leaky.py")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "ANCHOR LEAK: 1 " in r.stdout and "extworld_server" in r.stdout, r.stdout
    pid = int(r.stdout.split("still alive: [")[1].split("]")[0])
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_foreign_external_world_not_counted_or_killed(tmp_path):
    foreign = tempfile.mkdtemp(prefix="foreign")
    (Path(foreign) / "s.json").write_text(json.dumps(load_systems("manufacturing")))
    p = subprocess.Popen([sys.executable, "-m", "r3_shared.extworld_server", "--dir", f"{foreign}/ext", "--systems", f"{foreign}/s.json",
                          "--socket", f"{foreign}/s"], env={**os.environ, "PYTHONPATH": str(SRC)}, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, start_new_session=True)
    try:
        assert p.stdout.readline().startswith(b"READY")
        r = _session(tmp_path, "def test_noop():\n    assert True\n", "test_clean.py")
        assert r.returncode == 0 and "ANCHOR LEAK" not in r.stdout, r.stdout + r.stderr
        assert p.poll() is None
    finally:
        p.kill()
        p.wait()
        shutil.rmtree(foreign, ignore_errors=True)
