"""In-memory, deterministic fault-injection registry.

Used only by services/wms (docs/experiment/spec/06_decision_and_action_runtime.md
"WMS fake API requirements"), and only mounted when OO_TEST_MODE=1. State is
process-local: the fault-injecting services run as a single uvicorn worker
process (no multi-worker fan-out), so a plain, lock-guarded dict is enough —
no need for a shared store across processes.

Two arming scopes:
  * "next_n": the next N requests to the armed endpoint, in FIFO order,
    regardless of their action_execution_id.
  * "action_execution_id": a single specific key. Consumed (removed) the
    first time a request with that key is seen, so a client retry after the
    fault fires goes through the normal path.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class ArmedFault:
    mode: str
    params: Mapping[str, Any]


class FaultRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_n: deque[ArmedFault] = deque()
        self._by_key: dict[str, ArmedFault] = {}

    def arm(
        self,
        mode: str,
        scope: str,
        n: int = 1,
        action_execution_id: Optional[str] = None,
        params: Optional[Mapping[str, Any]] = None,
    ) -> None:
        fault = ArmedFault(mode=mode, params=dict(params or {}))
        with self._lock:
            if scope == "next_n":
                for _ in range(max(1, n)):
                    self._next_n.append(fault)
            elif scope == "action_execution_id":
                if not action_execution_id:
                    raise ValueError("action_execution_id required for this scope")
                self._by_key[action_execution_id] = fault
            else:
                raise ValueError(f"unknown fault scope: {scope}")

    def resolve(self, action_execution_id: str) -> Optional[ArmedFault]:
        """Consume and return the fault (if any) that applies to this
        request. Key-scoped faults take priority over queued next_n ones."""
        with self._lock:
            keyed = self._by_key.pop(action_execution_id, None)
            if keyed is not None:
                return keyed
            if self._next_n:
                return self._next_n.popleft()
            return None

    def reset(self) -> None:
        with self._lock:
            self._next_n.clear()
            self._by_key.clear()

    def snapshot(self) -> Mapping[str, Any]:
        with self._lock:
            return {
                "next_n": [f.mode for f in self._next_n],
                "by_key": {k: f.mode for k, f in self._by_key.items()},
            }


registry = FaultRegistry()
