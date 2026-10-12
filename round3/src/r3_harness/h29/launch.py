"""Launcher logic of scripts/run_h29.py (ONE entry point for dev, smoke and official runs; only ids and sizes differ - G3-E31b).
guard() REFUSES (Refusal -> exit 2, no evidence written) a non-dev id when ANY of: a service of any worker set is unreachable; HEAD != candidate
tag; a FREEZE_G5 hash mismatches; a file of the freeze manifest (s9) is missing from FREEZE_G5; dev overrides present; sizes below the frozen
floors; the out dir exists; the multiprocessing start method is not spawn. Every dev/non-dev branch of evaluator.py (DEV_BRANCHES) is
mirrored here as a Refusal with the same branch name (G4-E27)."""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import subprocess
from pathlib import Path

from r3_shared.anchor import AnchorClient
from r3_shared.authsvc import AuthorityClient
from r3_shared.extworld import ExternalClient

from . import evalchecks as EC, runner

ROUND3 = Path(__file__).resolve().parents[3]


class Refusal(Exception):
    def __init__(self, branch: str, msg: str):
        super().__init__(f"refusing [{branch}]: {msg}")
        self.branch = branch


def is_dev(exp_id: str) -> bool:
    return "-dev" in exp_id


def git(*a) -> str:
    return subprocess.check_output(["git", "-C", str(ROUND3), *a], text=True).strip()


def services_up(root: str, W: int) -> list:
    """Unreachable services of the W launcher-started sets (empty = all answer)."""
    down = []
    for i in range(W):
        svc = runner.services_for(root, i)
        for name, fn in (("anchor", lambda s=svc: AnchorClient(s.anchor_sock)._call({"op": "ping"})), ("ext", lambda s=svc: ExternalClient(s.ext_sock).ping()),
                         ("auth", lambda s=svc: AuthorityClient(s.auth_sock_path, "probe").ping())):
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                down.append(f"{name}-{i}: {exc}")
    return down


def guard(a, out: Path, env=None) -> dict:
    """-> dev overrides dict ({} for full-size). Raises Refusal(branch, ...)."""
    env = os.environ if env is None else env
    dev = is_dev(a.exp_id)
    ov = EC.overrides_for(a.sequences, a.controls, a.boundary)
    if (ov or a.dev_overrides) and not dev:
        raise Refusal("size_overrides", f"dev overrides / sizes below the frozen floors {EC.SIZES} are allowed only for dev experiment ids "
                                        f"(containing '-dev'), not {a.exp_id!r}")
    if dev:
        return ov
    if mp.get_start_method(allow_none=True) not in (None, "spawn"):
        raise Refusal("start_method", "multiprocessing start method must be spawn")
    root, W = env.get("R3_H29_SVC"), int(env.get("R3_H29_WORKERS", "0") or 0)
    if not root or W < 1:
        raise Refusal("service_presence", "non-dev id needs the launcher-started service sets (R3_H29_SVC, R3_H29_WORKERS): use scripts/run_h29.sh")
    down = services_up(root, W)
    if down:
        raise Refusal("service_presence", f"anchor / ExternalWorld / AuthorityService not reachable: {down[:3]}")
    if not a.candidate_tag:
        raise Refusal("candidate_tag", "non-dev id needs --candidate-tag")
    try:
        if git("rev-parse", "HEAD") != git("rev-parse", a.candidate_tag + "^{commit}"):
            raise Refusal("candidate_tag", f"HEAD != {a.candidate_tag}")
    except subprocess.CalledProcessError:
        raise Refusal("candidate_tag", f"candidate tag {a.candidate_tag} not found") from None
    frozen, cur = EC.freeze_state()
    drift = [f for f, h in frozen.items() if cur.get(f) != h]
    if drift:
        raise Refusal("freeze_hash", f"FREEZE_G5 hashes mismatch: {drift}")
    ms = EC.manifest_state()
    if ms["missing_from_freeze"] or ms["missing_on_disk"]:
        raise Refusal("freeze_manifest", f"freeze-manifest files absent from FREEZE_G5 or from disk: {(ms['missing_from_freeze'] + ms['missing_on_disk'])[:5]}")
    fz, ch = EC.catalogue_state()
    if fz is None or fz != ch:
        raise Refusal("freeze_hash", "H28 adapter catalogue is not frozen in FREEZE_G4 or its sha256 differs")
    if (out / "cases.jsonl").exists() or (out / "cases.jsonl.gz").exists() or (out / "run-pre.json").exists():
        raise Refusal("out_dir", f"{out} already holds evidence")
    return ov


def candidate_record(a) -> dict:
    if not a.candidate_tag:
        return {"tag": None, "head_matches_tag": False}
    try:
        return {"tag": a.candidate_tag, "head_matches_tag": git("rev-parse", "HEAD") == git("rev-parse", a.candidate_tag + "^{commit}")}
    except subprocess.CalledProcessError:
        return {"tag": a.candidate_tag, "head_matches_tag": False}
