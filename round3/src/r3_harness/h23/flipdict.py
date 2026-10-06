"""A caller-controlled args mapping that changes under the variant's feet (time-of-check/time-of-use attack).

Each flipped key returns its benign value on the FIRST read and the hostile value on every later read, so a variant
that copies args once at entry (the correct design) sees only benign values; one that re-reads the caller's object
after authorization commits hostile values. Public-interface only: it is just a dict the caller passed.
"""
from __future__ import annotations


class FlipDict(dict):
    def __init__(self, benign: dict, hostile: dict):
        super().__init__(benign)
        self._hostile = dict(hostile)
        self._reads: dict[str, int] = {}

    def _read(self, key):
        n = self._reads.get(key, 0)
        self._reads[key] = n + 1
        if n >= 1 and key in self._hostile:
            return self._hostile[key]
        return dict.__getitem__(self, key)

    def __getitem__(self, key):
        return self._read(key)

    def get(self, key, default=None):
        return self._read(key) if key in self else default

    def items(self):
        return [(k, self._read(k)) for k in dict.keys(self)]

    def values(self):
        return [self._read(k) for k in dict.keys(self)]

    def copy(self):
        return dict(self.items())

    def reads(self) -> dict:
        return dict(self._reads)
