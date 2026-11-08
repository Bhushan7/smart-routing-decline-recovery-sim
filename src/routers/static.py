from __future__ import annotations

from ..simulator.types import RouterState, Transaction
from .base import NullObserve


class StaticRouter(NullObserve):
    """Fixed primary PSP. Pair with FailoverRecovery for technical-error failover."""

    def __init__(self, primary: int = 2):
        self.primary = primary

    def route(self, txn: Transaction, state: RouterState) -> int:
        return self.primary
