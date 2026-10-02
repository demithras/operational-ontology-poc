"""Hypothesis profiles (dev / ci) and the shared small-run evidence fixture for the H16 evaluator tests."""
import copy
import json
import os
import shutil
import sys
from pathlib import Path

import pytest
from hypothesis import HealthCheck, settings

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_SUPPRESS = [HealthCheck.too_slow, HealthCheck.data_too_large, HealthCheck.filter_too_much, HealthCheck.large_base_example]
settings.register_profile("dev", max_examples=200, deadline=None, suppress_health_check=_SUPPRESS, database=None)
settings.register_profile("ci", max_examples=200, deadline=None, derandomize=True, suppress_health_check=_SUPPRESS, database=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))


@pytest.fixture(scope="session")
def positive_dir(tmp_path_factory):
    """A synthetic known-positive: a REAL small run (60 cases) whose case rows are padded to 2,000 distinct rows."""
    from eoo_exp import provenance as prov
    from eoo_exp.util import canon, sha_text
    from eoo_h16 import run as runner
    d = tmp_path_factory.mktemp("h16pos") / "pos"
    runner.run(16, 60, d.parent, "pos")
    rec = json.loads((d / "mixed-domain-generated.json").read_text())
    rows = rec["payload"]["cases"]
    base = [r for r in rows if r["valid"] and r["loaded"]]
    i = 0
    while len(rows) < 2100:
        r = copy.deepcopy(base[i % len(base)])
        r["sha"] = f"pad{i:013d}"
        rows.append(r)
        i += 1
    rec["payload_hash"] = sha_text(canon(rec["payload"]))
    prov.write(d, "mixed-domain-generated.json", rec)
    return d


@pytest.fixture()
def edit(positive_dir, tmp_path):
    """edit(filename, fn) -> new evidence dir where fn(payload) edited that file's payload (hash refreshed)."""
    from eoo_exp import provenance as prov
    from eoo_exp.util import canon, sha_text

    def _edit(filename=None, fn=None, record_fn=None, drop=None):
        dst = tmp_path / "ev"
        shutil.copytree(positive_dir, dst)
        if drop:
            (dst / drop).unlink()
        if filename:
            rec = json.loads((dst / filename).read_text())
            if fn:
                fn(rec["payload"])
                rec["payload_hash"] = sha_text(canon(rec["payload"]))
            if record_fn:
                record_fn(rec)
            prov.write(dst, filename, rec)
        return dst
    return _edit
