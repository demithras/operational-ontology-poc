"""Run in a SUBPROCESS against a mutated copy of the tree (PYTHONPATH points at it): prints the alias-invariance probe."""
from __future__ import annotations

import json
import sys

from . import alias, synth


def main(argv: list[str]) -> int:
    n = int(argv[0]) if argv else 150
    import eoo_engine
    out = alias.probe(synth.generate(11, n))
    out["engine_file"] = eoo_engine.__file__
    print("PROBE " + json.dumps(out, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
