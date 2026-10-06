"""The generated-corpus round trip over both surfaces (the 10,000-case part of the frozen run)."""
from __future__ import annotations

import sys
import time
from collections import Counter

from . import corpus, isolation
from .roundtrip import attempt, public
from .surfaces import SURFACES

KEEP = 2000  # packages kept (evenly strided over the whole corpus) for the sidecar audit, deletion mutants and mutation suite


class GenLoop:
    def __init__(self, requested: int = 10000, log=sys.stderr):
        self.log = log
        self.stride = max(1, requested // KEEP)
        self.ch = corpus.CorpusHash()
        self.cov: Counter = Counter()
        self.head: list[dict] = []
        self.tokens: set[str] = set()
        self.t0 = time.time()
        self.s = {n: {"ok": 0, "failed": 0, "unrepresentable": 0, "exact_equal": 0, "failed_by_kind": Counter(),
                      "failures_by_ir_path": Counter(), "first_failures": [], "t_render": 0.0, "t_compile": 0.0,
                      "shared_id_pkgs": 0, "shared_id_failed": 0} for n in SURFACES}

    def __call__(self, i: int, pkg: dict) -> None:
        try:
            self._one(i, pkg)
        except Exception as e:  # noqa: BLE001 - a harness bug must not look like a Hypothesis failure
            self.s["openpona"].setdefault("harness_errors", []).append(f"{i}: {type(e).__name__}: {str(e)[:120]}")
        if i % 500 == 0:
            print(f"[genloop] {i} packages, {time.time() - self.t0:.0f}s", file=self.log, flush=True)

    def _one(self, i: int, pkg: dict) -> None:
        self.ch.add(pkg)
        feats = corpus.features(pkg)
        self.cov.update(feats)
        if i % self.stride == 0 and len(self.head) < KEEP:
            self.head.append(pkg)
        shared = "function_and_action_share_id" in feats
        for name, surf in SURFACES.items():
            r = attempt(surf, pkg)
            d = self.s[name]
            d[r["status"]] += 1
            d["exact_equal"] += bool(r.get("exact"))
            d["t_render"] += r["t_render"]
            d["t_compile"] += r["t_compile"]
            if shared:
                d["shared_id_pkgs"] += 1
                d["shared_id_failed"] += r["status"] != "ok"
            if r["status"] != "ok":
                d["failed_by_kind"][r["kind"]] += 1
                d["failures_by_ir_path"].update(r["paths"])
                if len(d["first_failures"]) < 20:
                    d["first_failures"].append({"index": i, **public(r), "package": pkg})
            if name == "openpona" and "art" in r:
                self.tokens.update(r["art"][0].split())

    def payload(self, requested: int, seed: int, shrunk: dict) -> dict:
        n = max(1, self.ch.n)
        out = {"requested": requested, "seed": seed, "hypothesis_local_constants_isolated": isolation.LAST["isolated"],
               "generation": self.ch.result(),
               "valid_cases": self.ch.n - self.ch.invalid, "feature_coverage": corpus.coverage(self.cov),
               "tokens_seen_in_openpona_text": sorted(self.tokens), "surfaces": {}}
        for name, d in self.s.items():
            out["surfaces"][name] = {
                "ok": d["ok"], "failed": d["failed"], "unrepresentable": d["unrepresentable"],
                "exact_equal": d["exact_equal"], "failed_by_kind": dict(d["failed_by_kind"]),
                "failures_by_ir_path": dict(d["failures_by_ir_path"].most_common(50)),
                "function_action_shared_id": {"packages": d["shared_id_pkgs"], "not_ok": d["shared_id_failed"]},
                "first_failures": d["first_failures"], "minimal_counterexamples": shrunk.get(name, []),
                "mean_render_ms": 1000 * d["t_render"] / n, "mean_compile_ms": 1000 * d["t_compile"] / n,
                **({"harness_errors": d["harness_errors"][:10]} if d.get("harness_errors") else {})}
        return out

    def shrink(self, seed: int) -> dict:
        res = {}
        for name, surf in SURFACES.items():
            paths = list(self.s[name]["failures_by_ir_path"])
            res[name] = corpus.shrink_counterexamples(surf, seed, paths) if paths else []
        return res
