"""Immutable experiment output directories: write into .<id>.partial, then rename; refuse an existing dir."""
from __future__ import annotations

import os
import shutil
from contextlib import contextmanager
from pathlib import Path


class OutputExists(Exception):
    pass


@contextmanager
def immutable_dir(out_root: Path, exp_id: str):
    """Yield a partial directory; on clean exit rename it to <out_root>/<exp_id>. On error the partial is removed."""
    out = Path(out_root) / exp_id
    if out.exists():
        raise OutputExists(f"{out} exists (experiments are immutable; use a new --exp-id)")
    tmp = out.with_name("." + out.name + ".partial")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    try:
        yield tmp
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    os.rename(tmp, out)
