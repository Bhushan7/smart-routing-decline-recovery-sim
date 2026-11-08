from __future__ import annotations

from ..simulator.types import RouterState, Transaction
from ..simulator.world import World
from .base import NullObserve


class OracleRouter(NullObserve):
    """Knows hidden approval truth (including drift). Benchmark for regret only."""

    def __init__(self, world: World):
        self.choice = world.oracle_psp.tolist()

    def route(self, txn: Transaction, state: RouterState) -> int:
        return self.choice[txn.idx]
