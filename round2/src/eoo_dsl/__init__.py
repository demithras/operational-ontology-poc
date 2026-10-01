"""Direct typed DSL baseline for H15: YAML text whose keys are exactly the frozen IR fields."""
from .compiler import compile
from .emit import render
from .errors import DslError

__all__ = ["DslError", "compile", "render"]
