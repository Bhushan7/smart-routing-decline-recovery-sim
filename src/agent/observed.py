"""Observable running state used by the rules layer and the agent tools.

Everything here is learned from outcomes the operator would really see (first-attempt results,
retry results, response codes). It never reads hidden simulator truth.
"""
from __future__ import annotations

from collections import deque

import numpy as np

from ..simulator.config import ACTION_NAMES, CASCADE, N_PSP, N_SEGMENTS, PSPS, SimConfig
from ..simulator.types import Outcome, Transaction

# Rounded rules of thumb a payments team might hold before seeing its own data. Deliberately not the
# simulator's exact table. Learned retry outcomes override them as evidence accumulates.
PRIOR_STRENGTH = 20.0
GENERIC_PRIORS = {  # code family -> (retry_same_now, retry_same_delayed, cascade)
    "HARD": (0.0, 0.0, 0.0),
    "SOFT_INSUFFICIENT_FUNDS": (0.05, 0.25, 0.05),
    "SOFT_ISSUER_UNAVAILABLE": (0.25, 0.45, 0.30),
    "SOFT_AMOUNT_LIMIT": (0.03, 0.05, 0.05),
    "SOFT_VELOCITY": (0.05, 0.35, 0.10),
    "SOFT_AUTH_REQUIRED": (0.03, 0.05, 0.05),
    "TECH": (0.40, 0.55, 0.80),
    "AMBIGUOUS": (0.10, 0.15, 0.20),
}


def code_family(code: str) -> str:
    if code.startswith("HARD_"):
        return "HARD"
    if code.startswith("TECH_"):
        return "TECH"
    if code.startswith("AMBIGUOUS_"):
        return "AMBIGUOUS"
    return code


class ObservedState:
    def __init__(self, cfg: SimConfig, window: int = 500):
        self.cfg = cfg
        self.window = window
        self.win = [deque(maxlen=window) for _ in range(N_PSP)]  # (approved, tech_code)
        self.win_ok = np.zeros(N_PSP)
        self.win_tech = np.zeros(N_PSP)
        self.cum_ok = np.zeros(N_PSP)
        self.cum_n = np.zeros(N_PSP)
        self.seg_ok = np.zeros((N_SEGMENTS, N_PSP))
        self.seg_n = np.zeros((N_SEGMENTS, N_PSP))
        self.retry: dict[tuple[str, int], list[int]] = {}

    # ---- updates
    def observe_attempt(self, txn: Transaction, psp: int, outcome: Outcome) -> None:
        tech = int(bool(outcome.code and outcome.code.startswith("TECH_")))
        ok = int(outcome.approved)
        w = self.win[psp]
        if len(w) == w.maxlen:
            old_ok, old_tech = w[0]
            self.win_ok[psp] -= old_ok
            self.win_tech[psp] -= old_tech
        w.append((ok, tech))
        self.win_ok[psp] += ok
        self.win_tech[psp] += tech
        self.cum_ok[psp] += ok
        self.cum_n[psp] += 1
        self.seg_ok[txn.segment, psp] += ok
        self.seg_n[txn.segment, psp] += 1

    def observe_retry(self, code: str, kind: int, ok: bool) -> None:
        rec = self.retry.setdefault((code_family(code), kind), [0, 0])
        rec[0] += int(ok)
        rec[1] += 1

    # ---- queries
    def psp_health(self) -> list[dict]:
        out = []
        for j in range(N_PSP):
            n = len(self.win[j])
            rate = self.win_ok[j] / n if n else None
            tech = self.win_tech[j] / n if n else None
            base = self.cum_ok[j] / self.cum_n[j] if self.cum_n[j] else None
            degraded = bool(n >= 100 and (tech > 0.05 or (base is not None and rate < base - 0.07)))
            out.append({"psp": PSPS[j], "recent_approval_rate": None if rate is None else round(rate, 3),
                        "recent_technical_error_rate": None if tech is None else round(tech, 3),
                        "recent_attempts": n, "degraded": degraded})
        return out

    def is_degraded(self, psp: int) -> bool:
        return self.psp_health()[psp]["degraded"]

    def segment_stats(self, txn: Transaction) -> list[dict]:
        out = []
        for j in range(N_PSP):
            n = self.seg_n[txn.segment, j]
            out.append({"psp": PSPS[j], "attempts": int(n),
                        "approval_rate": None if n < 20 else round(self.seg_ok[txn.segment, j] / n, 3)})
        return out

    def retry_estimate(self, code: str, kind: int) -> tuple[float, int]:
        """Blend of the rule-of-thumb prior and observed retry outcomes for (code family, action)."""
        fam = code_family(code)
        prior = GENERIC_PRIORS.get(fam, GENERIC_PRIORS["AMBIGUOUS"])[min(kind, 2)]
        s, n = self.retry.get((fam, kind), [0, 0])
        return (prior * PRIOR_STRENGTH + s) / (PRIOR_STRENGTH + n), n

    def expected_value(self, txn: Transaction, psp: int, code: str, kind: int, target: int | None) -> float:
        c = self.cfg
        p, _ = self.retry_estimate(code, kind)
        tgt = target if kind == CASCADE and target is not None else psp
        if kind == 1 and not txn.recurring:
            p *= 1.0 - c.delay_abandon
        amt = c.amount_value[txn.amount_band]
        return p * (c.margin[txn.amount_band] - c.pct_fee[tgt] * amt) - c.fixed_fee[tgt] - c.retry_cost

    def best_alternative_psp(self, psp: int) -> int:
        """Healthiest other PSP by recent approval rate (ties: cheaper fixed fee)."""
        health = self.psp_health()
        cands = [j for j in range(N_PSP) if j != psp]

        def score(j):
            h = health[j]
            r = h["recent_approval_rate"] if h["recent_approval_rate"] is not None else 0.8
            return (not h["degraded"], r, -self.cfg.fixed_fee[j])

        return max(cands, key=score)


__all__ = ["ObservedState", "code_family", "ACTION_NAMES"]
