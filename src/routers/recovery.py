"""Recovery policies for declines (separate from first-attempt routing)."""
from __future__ import annotations

from ..simulator.config import CASCADE, RETRY_NOW, STOP
from ..simulator.types import Action, RouterState, Transaction
from ..simulator.world import World


class FailoverRecovery:
    """Fail over to a fixed secondary PSP on technical-error codes only."""

    def __init__(self, secondary: int = 0, fallback: int = 2):
        self.secondary = secondary
        self.fallback = fallback

    def decide(self, txn: Transaction, psp: int, code: str, state: RouterState) -> Action:
        if code.startswith("TECH_"):
            tgt = self.secondary if psp != self.secondary else self.fallback
            return Action(CASCADE, tgt)
        return Action(STOP)


class OracleRecovery:
    """Uses hidden truth to pick the highest-expected-value action. Benchmark only."""

    def __init__(self, world: World):
        self.world = world

    def decide(self, txn: Transaction, psp: int, code: str, state: RouterState) -> Action:
        cause = self.world.first_attempt(txn.idx, psp)
        return self.world.best_action(txn.idx, psp, cause)


class AlwaysRetryNow:
    """Test helper: naively retries every decline on the same PSP."""

    def decide(self, txn: Transaction, psp: int, code: str, state: RouterState) -> Action:
        return Action(RETRY_NOW)


__all__ = ["FailoverRecovery", "OracleRecovery", "AlwaysRetryNow", "STOP"]
