"""Variant registry, resolved lazily. Test fakes are never registered here."""
from __future__ import annotations

import importlib

VARIANTS = {"paladin": "paladin.variant:PaladinVariant",
            "conventional": "conventional.variant:ConventionalVariant"}


def load_variant(name: str):
    """Return a Variant instance. Raises KeyError for unknown names, NotImplementedError if not built yet."""
    if name not in VARIANTS:
        raise KeyError(f"unknown variant {name!r}; registered: {sorted(VARIANTS)}")
    mod_name, cls_name = VARIANTS[name].split(":")
    try:
        mod = importlib.import_module(mod_name)
    except ModuleNotFoundError as exc:
        if exc.name == mod_name:
            raise NotImplementedError(f"variant {name!r} not implemented yet ({mod_name} missing; arrives in P2)") from exc
        raise
    try:
        cls = getattr(mod, cls_name)
    except AttributeError as exc:
        raise NotImplementedError(f"variant {name!r} not implemented yet ({mod_name}.{cls_name} missing)") from exc
    return cls()
