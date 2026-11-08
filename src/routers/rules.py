"""Rule-based router: rules by coarse segment, fitted from OBSERVABLE early traffic.

Rules key = (region, amount_band, recurring). They are built from the first 10% of a dev-seed run
where traffic is spread uniformly over PSPs, using only observed outcomes and known fees.
Hidden truth is never read. The table is frozen in rule_table.json.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ..simulator.config import N_PSP, SimConfig
from ..simulator.types import Outcome, RouterState, Transaction
from ..simulator.world import World

TABLE_PATH = Path(__file__).with_name("rule_table.json")
CALIBRATION_FRACTION = 0.10
CALIBRATION_SEED = 1000  # a dev seed


def rule_key(txn: Transaction) -> str:
    return f"{txn.region},{txn.amount_band},{txn.recurring}"


class RuleBasedRouter:
    def __init__(self, table: dict[str, int] | None = None, default_psp: int = 2):
        self.table = table if table is not None else json.loads(TABLE_PATH.read_text())["table"]
        self.default_psp = default_psp

    def route(self, txn: Transaction, state: RouterState) -> int:
        return self.table.get(rule_key(txn), self.default_psp)

    def observe(self, txn: Transaction, psp: int, outcome: Outcome) -> None:
        return None


class _Calibrator:
    """Uniform-random traffic that records observed net value per (rule key, PSP)."""

    def __init__(self, cfg: SimConfig, seed: int):
        self.cfg = cfg
        self.rng = np.random.default_rng(seed)
        self.sum: dict[tuple[str, int], float] = {}
        self.cnt: dict[tuple[str, int], int] = {}

    def route(self, txn: Transaction, state: RouterState) -> int:
        return int(self.rng.integers(0, N_PSP))

    def observe(self, txn: Transaction, psp: int, outcome: Outcome) -> None:
        c = self.cfg
        k = (rule_key(txn), psp)
        v = -c.fixed_fee[psp]
        if outcome.approved:
            v += c.margin[txn.amount_band] - c.pct_fee[psp] * c.amount_value[txn.amount_band]
        self.sum[k] = self.sum.get(k, 0.0) + v
        self.cnt[k] = self.cnt.get(k, 0) + 1


def fit_rule_table(cfg: SimConfig | None = None, seed: int = CALIBRATION_SEED) -> dict[str, int]:
    from ..simulator.engine import run
    from .base import NoRecovery

    cfg = cfg or SimConfig()
    world = World(cfg, seed)
    cal = _Calibrator(cfg, seed + 7)
    run(world, cal, NoRecovery(), n=int(cfg.n_txn * CALIBRATION_FRACTION))
    table = {}
    for r in range(3):
        for a in range(3):
            for rec in range(2):
                key = f"{r},{a},{rec}"
                means = [
                    cal.sum.get((key, j), 0.0) / max(1, cal.cnt.get((key, j), 0)) for j in range(N_PSP)
                ]
                table[key] = int(np.argmax(means))
    return table


def write_rule_table() -> None:
    table = fit_rule_table()
    TABLE_PATH.write_text(json.dumps(
        {"note": "fitted from observable first 10% of dev seed 1000; simulated", "table": table},
        indent=1, sort_keys=True))


if __name__ == "__main__":
    write_rule_table()
    print(TABLE_PATH.read_text())
