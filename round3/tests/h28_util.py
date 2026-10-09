"""In-process H28 corpus runner for tests: private ExternalWorld, fake/real variant factory, judge + aggregate."""
import json
import os
import tempfile
from pathlib import Path

from r3_harness.h28 import finalize, runner, specs
from r3_shared.extworld import start_external


def run_corpus(factory, cases=130, controls=14, seed=2811, observer_factory=None, mutants=()):
    d = Path(tempfile.mkdtemp(prefix="h28t"))
    (d / "systems.json").write_text(json.dumps(specs.combined_systems()))
    proc = start_external(d / "ext", d / "systems.json", os.path.join(tempfile.mkdtemp(prefix="r3t"), "s"))
    try:
        pre = runner.run_variant(factory, "t", d / "out", "exp-t-dev-1", seed, proc.sock_path, proc.ctl_path, str(d / "ext"),
                                 cases=cases, controls=controls, observer_factory=observer_factory, mutants=mutants)
    finally:
        closed = proc.close()
    J = finalize.judge_all(d / "out", str(d / "ext"), pre)
    return J, finalize.aggregate(J), closed, pre
