"""Ontology Toolchain (H21): generates typed SDK / query / action / agent surfaces from a validated IR package.

Generic code only: no domain knowledge. Everything domain-shaped is emitted into a build directory by ``build``.
This package imports neither the Engine nor the independent authority oracle (round2/oracles/h21).
"""
TOOLCHAIN_VERSION = "1.0"
from .build import build, load_generated  # noqa: E402,F401
