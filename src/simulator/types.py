"""Observable types shared by simulator, routers and agent. None of these expose hidden truth."""
from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple, Protocol

from .config import STOP


class Transaction(NamedTuple):
    idx: int  # position in the time-ordered stream
    bin_group: int
    card_type: int
    region: int
    amount_band: int
    recurring: int
    hour: int
    customer_id: int
    recent_declines: int  # observable decline history of this customer
    segment: int


class Outcome(NamedTuple):
    approved: bool
    code: str | None  # observed response code (None when approved)


class Action(NamedTuple):
    kind: int = STOP
    target_psp: int | None = None
    delay_s: int = 0


@dataclass
class RouterState:
    t: int = 0
    n_total: int = 0


class Router(Protocol):
    def route(self, txn: Transaction, state: RouterState) -> int: ...
    def observe(self, txn: Transaction, psp: int, outcome: Outcome) -> None: ...


class RecoveryPolicy(Protocol):
    def decide(self, txn: Transaction, psp: int, code: str, state: RouterState) -> Action: ...
