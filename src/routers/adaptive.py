"""Adaptive router: Thompson sampling on expected net value, with guardrails.

- Beta posterior on approval probability per (segment, PSP).
- Hierarchical backoff: segment -> (region, bin_group) -> global per PSP. A sparse arm borrows its
  prior mean from its parent, with strength capped at `prior_strength` pseudo-observations.
- Reward = p * (margin - pct_fee * amount) - fixed_fee. Fees are known to the router; only the
  approval probability is learned. Hidden truth is never read.
- Non-stationarity: per-arm exponential discounting of evidence (`decay`).
- Guardrails: per-PSP traffic cap over a rolling window, and a uniform exploration floor.
"""
from __future__ import annotations

import json
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from ..simulator.config import N_PSP, N_SEGMENTS, SimConfig
from ..simulator.types import Outcome, RouterState, Transaction

PARAMS_PATH = Path(__file__).with_name("adaptive_params.json")


@dataclass
class AdaptiveParams:
    decay: float = 0.999
    prior_strength: float = 20.0
    explore_floor: float = 0.02
    traffic_cap: float = 0.60
    cap_window: int = 2000

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
        shape = {"seg": (N_SEGMENTS, N_PSP), "mid": (12, N_PSP), "glob": (N_PSP,)}
        self.s = {k: np.zeros(v) for k, v in shape.items()}
        self.f = {k: np.zeros(v) for k, v in shape.items()}
        self.window: deque[int] = deque(maxlen=self.p.cap_window)
        self.counts = np.zeros(N_PSP, dtype=np.int64)
        self.n_explore = 0
        self.n_routed = 0

    # ------------------------------------------------------------ posterior
    def posterior_params(self, segment: int, region: int, bin_group: int):
        """Beta(a, b) per PSP for one segment, via hierarchical backoff."""
        k = self.p.prior_strength
        mid = region * 4 + bin_group
        g = (self.s["glob"] + 1.0) / (self.s["glob"] + self.f["glob"] + 2.0)
        ms, mf = self.s["mid"][mid], self.f["mid"][mid]
        m = (ms + k * g) / (ms + mf + k)
        a = self.s["seg"][segment] + k * m
        b = self.f["seg"][segment] + k * (1.0 - m)
        return a, b

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
            a, b = self.posterior_params(txn.segment, txn.region, txn.bin_group)
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
        for level, idx in (("seg", (txn.segment, psp)), ("mid", (txn.region * 4 + txn.bin_group, psp)),
                           ("glob", (psp,))):
            self.s[level][idx] = self.s[level][idx] * d + y
            self.f[level][idx] = self.f[level][idx] * d + (1.0 - y)
