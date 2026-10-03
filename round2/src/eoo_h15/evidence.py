"""Provenance, protocol pre-flight and evidence-record wrapping (schemas/evidence-record.schema.json)."""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import platform
import subprocess
import sys
from importlib.metadata import distribution, version
from pathlib import Path

from .util import REPO, ROOT, canon, sha_file, sha_text

REQUIRED = ("real-domain-roundtrip.json", "generated-roundtrip.json", "ambiguity-corpus.json", "sidecar-audit.json",
            "mutation-results.json", "compiler-diff-metrics.json")
KIND = {f: f[:-5] for f in REQUIRED}


def freeze_hash() -> str:
    """Recompute protocol_sha256 exactly as scripts/freeze_protocol.py does, from the files FREEZE.json lists."""
    fz = json.loads((ROOT / "protocol/FREEZE.json").read_text())
    h = hashlib.sha256()
    for f in fz["files"]:
        b = (ROOT / f["path"]).read_bytes()
        h.update(f["path"].encode() + b"\0" + b + b"\0")
    return h.hexdigest()


def candidate_hash() -> tuple[str, str]:
    c = json.loads((ROOT / "protocol/H15_CANDIDATE.json").read_text())
    h = hashlib.sha256()
    for e in c["files"]:
        h.update(e["path"].encode() + b"\0" + (ROOT / e["path"]).read_bytes() + b"\0")
    return h.hexdigest(), c["combined_sha256"]


def candidate_hash_v2(pin_path: Path) -> tuple[str, str, list[str]]:
    """(recomputed, pinned, problems) for the H15 v2 candidate pin (same hashing as candidate_hash)."""
    from .candidate import v2_files
    c = json.loads(Path(pin_path).read_text())
    listed = [e["path"] for e in c["files"]]
    problems = [] if sorted(listed) == sorted(v2_files()) else [
        f"pin lists {sorted(set(listed) ^ set(v2_files()))} differently from the v2 candidate file set"]
    h = hashlib.sha256()
    for e in c["files"]:
        h.update(e["path"].encode() + b"\0" + (ROOT / e["path"]).read_bytes() + b"\0")
    return h.hexdigest(), c["combined_sha256"], problems


def head_commit() -> str:
    git = REPO / ".git"
    dirs = [git]
    if git.is_file():  # a linked worktree: '.git' is 'gitdir: <dir>'; refs may live in the common dir
        gd = Path(git.read_text().split(":", 1)[1].strip())
        gd = gd if gd.is_absolute() else (REPO / gd).resolve()
        dirs = [gd]
        if (gd / "commondir").is_file():
            cd = Path((gd / "commondir").read_text().strip())
            dirs.append(cd if cd.is_absolute() else (gd / cd).resolve())
    head = (dirs[0] / "HEAD").read_text().strip()
    if not head.startswith("ref:"):
        return head
    ref = head.split(" ", 1)[1]
    for d in dirs:
        if (d / ref).exists():
            return (d / ref).read_text().strip()
    for d in dirs:
        if (d / "packed-refs").exists():
            for ln in (d / "packed-refs").read_text().splitlines():
                if ln.endswith(" " + ref):
                    return ln.split()[0]
    raise RuntimeError(f"cannot resolve {ref}")


def dirty_paths() -> list[str]:
    out = subprocess.run(["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True, timeout=60).stdout
    return sorted(ln[3:] for ln in out.splitlines() if not ln[3:].startswith("round2/experiments/"))


def openpona_install() -> dict:
    import openpona
    du = json.loads(distribution("openpona-language-corpus").read_text("direct_url.json"))
    pkg = Path(openpona.__file__).parent
    return {"commit": du["vcs_info"]["commit_id"], "url": du["url"], "tokens_csv_sha256": sha_file(pkg / "tokens.csv"),
            "grammar_lark_sha256": sha_file(pkg / "grammar.lark"), "parser_py_sha256": sha_file(pkg / "parser.py")}


def preflight() -> dict:
    """Refuse (raise) on any protocol / candidate / pin mismatch. Returns the provenance facts."""
    fz = json.loads((ROOT / "protocol/FREEZE.json").read_text())
    bad = [f["path"] for f in fz["files"] if sha_file(ROOT / f["path"]) != f["sha256"]]
    if bad or freeze_hash() != fz["protocol_sha256"]:
        raise SystemExit(f"REFUSED: FREEZE.json mismatch {bad}")
    r = subprocess.run([sys.executable, str(ROOT / "scripts/h15_gate0_hash.py"), "--check"], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise SystemExit("REFUSED: Gate-0 check failed\n" + r.stdout + r.stderr)
    from . import candidate
    if candidate.is_v2():
        pin_path = candidate.pin_path()
        if not pin_path.is_file():
            raise SystemExit(f"REFUSED: no H15 v2 candidate pin at {pin_path} (scripts/h15_v2_candidate.py --write)")
        got, want, probs = candidate_hash_v2(pin_path)
        if got != want or probs:
            raise SystemExit(f"REFUSED: v2 candidate hash {got} != pin {want} ({pin_path}) {probs}")
    else:
        got, want = candidate_hash()
        if got != want:
            raise SystemExit(f"REFUSED: candidate hash {got} != H15_CANDIDATE.json {want}")
    pin = json.loads((ROOT / "hypotheses/h15/contract.json").read_text())["experiment"]["openpona_pin"]
    inst = openpona_install()
    if not (inst["commit"].startswith(pin["commit"]) and inst["tokens_csv_sha256"] == pin["tokens_csv_sha256"]
            and inst["grammar_lark_sha256"] == pin["grammar_lark_sha256"]):
        raise SystemExit(f"REFUSED: installed OpenPona differs from the pin: {inst}")
    g0 = json.loads((ROOT / "protocol/H15_GATE0.json").read_text())
    out = {"protocol_freeze_hash": fz["protocol_sha256"], "gate0_combined_sha256": g0["combined_sha256"],
           "candidate_combined_sha256": got, "openpona_pin": pin, "openpona_installed": inst,
           "gate0_check": r.stdout.strip().splitlines()[-1]}
    if candidate.is_v2():
        out["v2"] = {"candidate_surface": "openpona2", "candidate_pin_path": str(candidate.pin_path()),
                     "h15_v2_prereg_sha256": sha_file(ROOT / "protocol/H15_V2_PREREG.json")}
    return out


def harness_hashes() -> dict:
    files = sorted((ROOT / "src/eoo_h15").glob("*.py")) + [ROOT / "scripts/run_h15.py", ROOT / "scripts/evaluate_h15.py"]
    return {f.relative_to(ROOT).as_posix(): sha_file(f) for f in files if f.exists()}


def environment() -> dict:
    env = {"python": sys.version.split()[0], "platform": platform.platform(), "machine": platform.machine()}
    for pkg in ("hypothesis", "jsonschema", "pyyaml", "openpona-language-corpus"):
        try:
            env[pkg] = version(pkg)
        except Exception:  # noqa: BLE001
            env[pkg] = None
    return env


def provenance(pre: dict, exp_id: str, seed: int, corpus_hash: str) -> dict:
    dirty = dirty_paths()
    v2 = pre.get("v2")
    if v2:  # H15 v2: the candidate surface and the v2 preregistration travel with every record
        return {**_prov(pre, exp_id, seed, corpus_hash, dirty), **v2}
    return _prov(pre, exp_id, seed, corpus_hash, dirty)


def _prov(pre: dict, exp_id: str, seed: int, corpus_hash: str, dirty: list) -> dict:
    return {"experiment_id": exp_id, "hypothesis_id": "H15", "git_commit": head_commit(),
            "protocol_freeze_hash": pre["protocol_freeze_hash"], "environment": environment(), "seed": seed,
            "input_corpus_hash": corpus_hash, "oracle_version": "eoo_ir@gate0:" + pre["gate0_combined_sha256"],
            "variant_versions": {"openpona": {"candidate_combined_sha256": pre["candidate_combined_sha256"],
                                              "pin": pre["openpona_pin"]["commit"], "installed": pre["openpona_installed"]},
                                 "dsl": {"gate0_combined_sha256": pre["gate0_combined_sha256"]}},
            "gate0_combined_sha256": pre["gate0_combined_sha256"],
            "candidate_combined_sha256": pre["candidate_combined_sha256"], "openpona_pin": pre["openpona_pin"],
            "harness_dirty": bool(dirty), "harness_dirty_paths": dirty, "harness_sha256": harness_hashes()}


def wrap(prov: dict, filename: str, payload: dict) -> dict:
    return {**prov, "evidence_kind": KIND[filename], "payload_hash": sha_text(canon(payload)), "payload_path": None,
            "created_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"), "payload": payload}


def write(dirpath: Path, filename: str, rec: dict) -> None:
    (dirpath / filename).write_text(json.dumps(rec, indent=1, sort_keys=True, ensure_ascii=True, default=_default) + "\n")


def _default(x):
    if isinstance(x, (set, frozenset)):
        return sorted(x)
    raise TypeError(f"not JSON serialisable: {type(x).__name__}")
