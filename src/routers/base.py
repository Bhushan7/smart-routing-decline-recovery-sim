"""Shared router helpers."""
from __future__ import annotations

from ..simulator.types import Action, Outcome, RouterState, Transaction


class NullObserve:
    def observe(self, txn: Transaction, psp: int, outcome: Outcome) -> None:
        return None


class NoRecovery:
    """Never retries."""

    def decide(self, txn: Transaction, psp: int, code: str, state: RouterState) -> Action:
        return Action()
