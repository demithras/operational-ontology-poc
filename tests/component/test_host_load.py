"""Phase 10a step 0b: services/common/host_load.py unit coverage. No docker
or stack required — `sample_host_load()` degrades to `docker_cpu_percent:
None` when the docker CLI/stack isn't reachable, which is itself part of
the contract under test (never a fabricated 0.0)."""

from __future__ import annotations

from services.common.host_load import HostLoadSample, contention_note, sample_host_load


def test_sample_host_load_returns_real_fields():
    sample = sample_host_load()
    assert isinstance(sample, HostLoadSample)
    assert sample.load_avg_1m >= 0.0
    assert sample.load_avg_5m >= 0.0
    assert sample.load_avg_15m >= 0.0
    assert sample.cpu_count >= 1
    assert sample.contended == (sample.load_avg_1m > sample.cpu_count)
    # docker_cpu_percent is either None (docker unreachable/no matching
    # containers) or a dict of container name -> float percent — never a
    # fabricated placeholder.
    assert sample.docker_cpu_percent is None or isinstance(sample.docker_cpu_percent, dict)


def test_sample_host_load_to_dict_round_trips_all_fields():
    sample = sample_host_load()
    d = sample.to_dict()
    assert set(d) == {"load_avg_1m", "load_avg_5m", "load_avg_15m", "cpu_count", "contended", "docker_cpu_percent"}


def test_contention_note_flags_contended_run():
    contended = HostLoadSample(240.0, 200.0, 150.0, 14, True, None)
    uncontended = HostLoadSample(1.0, 1.0, 1.0, 14, False, None)
    assert "CONTENDED" in contention_note(contended, uncontended)
    assert "NON-AUTHORITATIVE" in contention_note(contended, uncontended)
    assert "CONTENDED" not in contention_note(uncontended, uncontended)
