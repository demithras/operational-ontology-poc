"""The two H16 detectors, as functions of (sources | live process): kernel diff and domain-identity audit."""
from __future__ import annotations

import json

from eoo_exp.util import ROOT

from .audit import collect_tokens, exempt_words, read_dir, scan_sources


def kernel_diff(before: dict, after: dict) -> dict:
    """Diff of kernel kinds / dispatch / schema between two snapshots (rev_snapshot or live_snapshot)."""
    bk, ak = set(before["kernel_resource_kinds"]), set(after["kernel_resource_kinds"])
    bd, ad = before["dispatch"]["handlers"], after["dispatch"]["handlers"]
    bs, as_ = before["ir_schema"], after["ir_schema"]
    new_dispatch = sorted(set(ad) - set(bd))
    new_arrays = sorted(set(as_["resource_array_fields"]) - set(bs["resource_array_fields"]))
    new_kinds = sorted(set(new_dispatch) | set(new_arrays) | (ak - bk))
    changed = sorted(k for k in set(bd) & set(ad) if bd[k] != ad[k])
    return {
        "kernel_kinds_before": sorted(bk), "kernel_kinds_after": sorted(ak),
        "new_kernel_primitive_kinds": new_kinds, "new_kernel_primitive_kind_count": len(new_kinds),
        "removed_kinds": sorted((set(bd) - set(ad)) | (set(bs["resource_array_fields"]) - set(as_["resource_array_fields"])) | (bk - ak)),
        "dispatch_added": new_dispatch, "dispatch_removed": sorted(set(bd) - set(ad)),
        "dispatch_handlers_changed": changed, "dispatch_order_changed": before["dispatch"]["order"] != after["dispatch"]["order"],
        "schema_resource_arrays_added": new_arrays, "schema_defs_added": sorted(set(as_["defs"]) - set(bs["defs"])),
        "schema_defs_removed": sorted(set(bs["defs"]) - set(as_["defs"])),
        "schema_package_fields_added": sorted(set(as_["package_fields"]) - set(bs["package_fields"])),
        "schema_sha256_before": bs["sha256"], "schema_sha256_after": as_["sha256"],
        "schema_unchanged": bs["sha256"] == as_["sha256"],
        "dispatch_kinds_equal_schema_arrays": sorted(ad) == sorted(as_["resource_array_fields"]),
    }


def changed_is_clean(diff: dict) -> bool:
    return not (diff["new_kernel_primitive_kinds"] or diff["removed_kinds"] or diff["dispatch_handlers_changed"]
                or diff["schema_defs_added"] or diff["schema_defs_removed"] or diff["schema_package_fields_added"])


SCOPES = {"engine_core": "src/eoo_engine", "ir_core": "src/eoo_ir"}  # counted
INFO_SCOPES = {"dsl_compiler": "src/eoo_dsl", "openpona_compiler": "src/eoo_openpona"}  # reported, not counted


def audit_sources(overrides: dict | None = None, include_info: bool = False) -> dict:
    """Domain-identity audit of the counted scopes (``overrides`` = {relative path: mutated source text})."""
    tokens, exempt = collect_tokens(), exempt_words()
    out, total_branch, total_lit = {}, 0, 0
    for name, d in {**SCOPES, **(INFO_SCOPES if include_info else {})}.items():
        src = read_dir(ROOT / d)
        src.update({p: t for p, t in (overrides or {}).items() if p in src})
        r = scan_sources(src, tokens, exempt)
        out[name] = {k: v for k, v in r.items() if k != "hits"} | {"hits": r["hits"]}
        if name in SCOPES:
            total_branch += r["branch_hits"]
            total_lit += r["literal_hits"]
    return {"scopes": out, "domain_identity_branches": total_branch, "domain_identity_literals": total_lit,
            "token_count": len(tokens), "exempt_words_present_in_tokens": sorted(set(tokens) & exempt),
            "token_origins_sample": {t: tokens[t] for t in sorted(tokens)[:5]}}
