"""Generic, domain-blind Git-backed canonical store for the EOO Engine (adapter + deterministic projection)."""
from .adapter import GitAdapter, attach
from .errors import BatchError, ConflictError, RowRejected, StoreError
from .layout import artifact_digest
from .objects import Repo
from .store import GitStore

__all__ = ["BatchError", "ConflictError", "GitAdapter", "GitStore", "Repo", "RowRejected", "StoreError", "attach",
           "artifact_digest"]
