"""Independent backend-neutral EOO IR oracle (validate / normalize / equivalence / generators).

Contamination rule (AGENTS.md section 10): nothing in this package may import, mention or
depend on the candidate surface language under test.
"""
from .equivalence import EquivalenceResult, equivalent
from .normalize import normalize
from .validate import IRError, validate

__all__ = ["EquivalenceResult", "IRError", "equivalent", "normalize", "validate"]
