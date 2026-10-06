"""Source of choices for the attack rules: a seeded RNG (corpus driver) or hypothesis `data` (state machine)."""
from __future__ import annotations

import random


class RandChooser:
    def __init__(self, rng: random.Random):
        self.rng = rng

    def choice(self, seq):
        seq = list(seq)
        return seq[self.rng.randrange(len(seq))]

    def randint(self, a: int, b: int) -> int:
        return self.rng.randint(a, b)

    def chance(self, p: float) -> bool:
        return self.rng.random() < p


class HypChooser:
    def __init__(self, data):
        from hypothesis import strategies as st
        self._d, self._st = data, st

    def choice(self, seq):
        return self._d.draw(self._st.sampled_from(list(seq)))

    def randint(self, a: int, b: int) -> int:
        return self._d.draw(self._st.integers(a, b))

    def chance(self, p: float) -> bool:
        return self._d.draw(self._st.integers(0, 99)) < int(p * 100)
