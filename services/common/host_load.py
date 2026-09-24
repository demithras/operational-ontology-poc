"""Phase 10a step 0b: load-aware measurement helper.

The orchestrator's Phase 9 review found the host shared (load average
reaching 240 on 14 cores from unrelated processes) during a prior session.
Any latency/benchmark artifact this experiment writes must record host
load at start and end, and flag itself "contended" when the 1-minute load
average exceeds the core count — a benchmark run under contention is not
wrong, but its SLO verdict is not authoritative evidence about the system
under test.

Used by every latency/benchmark writer from this phase on (Phase 10b's
`make experiment` latency.json is the primary consumer per this phase's own
brief item 4/8; this phase's own stateful/mutation timing reports also use
it where relevant). Never imported by anything on the request hot path —
this is purely an out-of-band measurement annotation.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import asdict, dataclass
from typing import Optional


@dataclass(frozen=True)
class HostLoadSample:
    load_avg_1m: float
    load_avg_5m: float
    load_avg_15m: float
    cpu_count: int
    contended: bool
    docker_cpu_percent: Optional[dict[str, float]]

    def to_dict(self) -> dict:
        return asdict(self)


def _docker_cpu_percent(compose_project: str = "oo-poc", docker_config: Optional[str] = None) -> Optional[dict[str, float]]:
    """Best-effort `docker stats` snapshot (single sample, no streaming) for
    this compose project's own containers, keyed by container name. Returns
    None (never a fabricated 0.0) if docker/the CLI is unreachable — this is
    a diagnostic annex, not a gate, and an honest "unavailable" beats a
    silently wrong number (common.md honesty rule).
    """
    env = dict(os.environ)
    if docker_config:
        env["DOCKER_CONFIG"] = docker_config
    try:
        result = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{.Name}}\t{{.CPUPerc}}"],
            capture_output=True, text=True, timeout=10.0, env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    out: dict[str, float] = {}
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        name, pct = parts
        if compose_project not in name:
            continue
        try:
            out[name] = float(pct.strip().rstrip("%"))
        except ValueError:
            continue
    return out or None


def sample_host_load(docker_config: Optional[str] = None, compose_project: str = "oo-poc") -> HostLoadSample:
    """One point-in-time sample. Call once at the start and once at the end
    of any latency/benchmark run and record both — a single sample cannot
    tell you whether load was rising, falling, or a brief spike, which is
    exactly the ambiguity two samples resolve (same rationale as the
    "measured rate needs two samples" convention this experiment already
    follows for ETAs)."""
    load_1m, load_5m, load_15m = os.getloadavg()
    cpu_count = os.cpu_count() or 1
    return HostLoadSample(
        load_avg_1m=load_1m,
        load_avg_5m=load_5m,
        load_avg_15m=load_15m,
        cpu_count=cpu_count,
        contended=load_1m > cpu_count,
        docker_cpu_percent=_docker_cpu_percent(compose_project=compose_project, docker_config=docker_config),
    )


def contention_note(start: HostLoadSample, end: HostLoadSample) -> str:
    """Human-readable one-liner for embedding directly in a results JSON's
    own `notes`/`environment` block."""
    if start.contended or end.contended:
        return (
            f"CONTENDED: 1m load {start.load_avg_1m:.1f}->{end.load_avg_1m:.1f} "
            f"vs {start.cpu_count} cores — SLO verdicts from this run are reported "
            f"but NON-AUTHORITATIVE (docs/experiment/briefs/phase10a.md step 0b)."
        )
    return f"uncontended: 1m load {start.load_avg_1m:.1f}->{end.load_avg_1m:.1f} vs {start.cpu_count} cores."
