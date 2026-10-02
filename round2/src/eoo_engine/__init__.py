"""Generic EOO Engine: executes any valid IR package through kind-based dispatch (DISPATCH_TABLE).

No domain knowledge lives here: domain logic arrives as LogicBindings, external systems as adapters.
"""
from .authority import Principal
from .capabilities import WriteGrant
from .effects import AdapterRegistry
from .engine import ENGINE_VERSION, Engine, required_bindings
from .errors import (CapabilityError, EngineError, IntegrityError, InvalidRequest, LoadError, SimulatedCrash,
                     Unbound)
from .journal import Journal
from .logic import LogicBindings
from .registry import DISPATCH_TABLE

__all__ = ["ENGINE_VERSION", "AdapterRegistry", "CapabilityError", "DISPATCH_TABLE", "Engine", "EngineError", "IntegrityError",
           "InvalidRequest", "Journal", "LoadError", "LogicBindings", "Principal", "SimulatedCrash", "Unbound",
           "WriteGrant", "required_bindings"]
