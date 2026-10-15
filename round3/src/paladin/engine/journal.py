"""Durable JSONL journal + append-only logs (EffectLog, ProvenanceLog, ObservationLog).

Every state change of the Engine is one journal record, written (and flushed) BEFORE the change
is visible; an Engine rebuilt from the same journal replays to the same state.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator, Optional

from .canon import dumps, freeze, loads, to_plain


class Journal:
    def __init__(self, file: Optional[str | os.PathLike] = None):
        self.file = Path(file) if file is not None else None
        self.records: list[dict] = []
        if self.file is not None and self.file.exists():
            for line in self.file.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self.records.append(loads(line))

    def append(self, rec: dict) -> dict:
        rec = {"seq": len(self.records), **to_plain(rec)}
        line = dumps(rec)
        if self.file is not None:
            with self.file.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        self.records.append(rec)
        return rec

    def __iter__(self) -> Iterator[dict]:
        return iter(list(self.records))

    def __len__(self) -> int:
        return len(self.records)


class AppendOnlyLog:
    """Entries can be appended and read (as frozen copies); never changed or removed."""

    def __init__(self):
        self._entries: list = []

    def append(self, entry: dict) -> None:
        self._entries.append(freeze(to_plain(entry)))

    def entries(self) -> tuple:
        return tuple(self._entries)

    def where(self, **match) -> tuple:
        return tuple(e for e in self._entries if all(e.get(k) == v for k, v in match.items()))

    def __len__(self) -> int:
        return len(self._entries)
