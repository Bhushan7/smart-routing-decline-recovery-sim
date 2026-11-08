"""Adaptive router: Thompson sampling on expected net value, with guardrails.

- Beta posterior on approval probability per (segment, PSP).
- Hierarchical backoff over a configurable chain of learning keys (`levels`, coarsest to finest), then
  global per PSP. A sparse arm borrows its prior mean from its parent, with strength capped at
  `prior_strength` pseudo-observations. The finest level is the one sampled from. The simulator's
  144 segments are unaffected: only what the router learns on changes.
- Reward = p * (margin - pct_fee * amount) - fixed_fee. Fees are known to the router; only the
  approval probability is learned. Hidden truth is never read.
- Non-stationarity: per-arm exponential discounting of evidence (`decay`).
- Guardrails: per-PSP traffic cap over a rolling window, and a uniform exploration floor.
"""
from __future__ import annotations

import json
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from ..simulator.config import N_PSP, SimConfig
from ..simulator.types import Outcome, RouterState, Transaction

PARAMS_PATH = Path(__file__).with_name("adaptive_params.json")
RADIX = {"bin": 4, "card": 2, "region": 3, "amount": 3, "rec": 2}
DIMS = ("bin", "card", "region", "amount", "rec")
FULL = list(DIMS)
LEGACY_LEVELS = [["region", "bin"], FULL]  # Phase 3 design: 144 segments backing off to 12 cells


def _level_size(dims) -> int:
    n = 1
    for d in dims:
        n *= RADIX[d]
    return n


def _key(txn, dims) -> int:
    vals = {"bin": txn.bin_group, "card": txn.card_type, "region": txn.region,
            "amount": txn.amount_band, "rec": txn.recurring}
    k = 0
    for d in DIMS:
        if d in dims:
            k = k * RADIX[d] + vals[d]
    return k


@dataclass
class AdaptiveParams:
    decay: float = 0.999
    prior_strength: float = 20.0
    explore_floor: float = 0.02
    traffic_cap: float = 0.60
    cap_window: int = 2000
    levels: list = field(default_factory=lambda: [list(x) for x in LEGACY_LEVELS])

    @classmethod
    def load(cls) -> AdaptiveParams:
        if PARAMS_PATH.exists():
            return cls(**json.loads(PARAMS_PATH.read_text())["params"])
        return cls()

    def to_dict(self) -> dict:
        return asdict(self)


class AdaptiveRouter:
    def __init__(self, cfg: SimConfig, rng: np.random.Generator, params: AdaptiveParams | None = None):
        self.p = params or AdaptiveParams.load()
        self.rng = rng
        self.fixed = np.asarray(cfg.fixed_fee)
        self.pct = np.asarray(cfg.pct_fee)
        self.margin = np.asarray(cfg.margin)
        self.amount = np.asarray(cfg.amount_value)
        self.levels = [tuple(x) for x in self.p.levels]
        self.s = [np.zeros((_level_size(d), N_PSP)) for d in self.levels]
        self.f = [np.zeros((_level_size(d), N_PSP)) for d in self.levels]
        self.gs = np.zeros(N_PSP)
        self.gf = np.zeros(N_PSP)
        self.window: deque[int] = deque(maxlen=self.p.cap_window)
        self.counts = np.zeros(N_PSP, dtype=np.int64)
        self.n_explore = 0
        self.n_routed = 0

    # ------------------------------------------------------------ posterior
    def posterior_params(self, txn: Transaction):
        """Beta(a, b) per PSP for this transaction's finest learning cell, via hierarchical backoff."""
        k = self.p.prior_strength
        m = (self.gs + 1.0) / (self.gs + self.gf + 2.0)
        last = len(self.levels) - 1
        for i, dims in enumerate(self.levels):
            key = _key(txn, dims)
            ss, ff = self.s[i][key], self.f[i][key]
            if i == last:
                return ss + k * m, ff + k * (1.0 - m)
            m = (ss + k * m) / (ss + ff + k)

    # ------------------------------------------------------------ interface
    def route(self, txn: Transaction, state: RouterState) -> int:
        n_win = len(self.window)
        if n_win >= 100:
            allowed = self.counts < self.p.traffic_cap * n_win
            if not allowed.any():
                allowed = np.ones(N_PSP, dtype=bool)
        else:
            allowed = np.ones(N_PSP, dtype=bool)
        self.n_routed += 1
        if self.rng.random() < self.p.explore_floor:
            self.n_explore += 1
            choice = int(self.rng.choice(np.flatnonzero(allowed)))
        else:
            a, b = self.posterior_params(txn)
            p = self.rng.beta(a, b)
            unit = self.margin[txn.amount_band] - self.pct * self.amount[txn.amount_band]
            value = np.where(allowed, p * unit - self.fixed, -np.inf)
            choice = int(value.argmax())
        if len(self.window) == self.window.maxlen:
            self.counts[self.window[0]] -= 1
        self.window.append(choice)
        self.counts[choice] += 1
        return choice

    def observe(self, txn: Transaction, psp: int, outcome: Outcome) -> None:
        y = 1.0 if outcome.approved else 0.0
        d = self.p.decay
        for i, dims in enumerate(self.levels):
            key = _key(txn, dims)
            self.s[i][key, psp] = self.s[i][key, psp] * d + y
            self.f[i][key, psp] = self.f[i][key, psp] * d + (1.0 - y)
        self.gs[psp] = self.gs[psp] * d + y
        self.gf[psp] = self.gf[psp] * d + (1.0 - y)
