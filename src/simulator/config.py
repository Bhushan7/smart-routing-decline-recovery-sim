"""Simulator configuration. All values are synthetic (see docs/simulator-assumptions.md)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

PSPS = ("PSP_A", "PSP_B", "PSP_C", "PSP_D")
BIN_GROUPS = tuple(f"BIN_GROUP_{i}" for i in range(1, 5))
CARD_TYPES = ("debit", "credit")
REGIONS = ("REGION_1", "REGION_2", "REGION_3")
AMOUNT_BANDS = ("low", "mid", "high")
N_PSP = len(PSPS)
N_SEGMENTS = 4 * 2 * 3 * 3 * 2  # 144

# Hidden true causes (generic internal taxonomy; a simplified model, not network rules).
CAUSES = (
    "HARD_STOLEN_CARD", "HARD_INVALID_CARD", "HARD_CLOSED_ACCOUNT", "HARD_FRAUD_SUSPECTED",
    "SOFT_INSUFFICIENT_FUNDS", "SOFT_ISSUER_UNAVAILABLE", "SOFT_AMOUNT_LIMIT",
    "SOFT_VELOCITY", "SOFT_AUTH_REQUIRED",
    "TECH_PSP_TIMEOUT", "TECH_NETWORK_ERROR", "TECH_PSP_DEGRADED",
)
HARD_CAUSES = (0, 1, 2, 3)
SOFT_CAUSES = (4, 5, 6, 7, 8)
TECH_CAUSES = (9, 10, 11)
AMBIGUOUS_CODES = ("AMBIGUOUS_GENERIC_DECLINE", "AMBIGUOUS_DO_NOT_HONOR")

# Action kinds
RETRY_NOW, RETRY_DELAYED, CASCADE, STOP = 0, 1, 2, 3
ACTION_NAMES = ("retry_same_now", "retry_same_delayed", "cascade", "stop")


def cause_class(cause: int) -> str:
    if cause in HARD_CAUSES:
        return "hard"
    if cause in SOFT_CAUSES:
        return "soft"
    return "tech"


@dataclass
class SimConfig:
    n_txn: int = 300_000
    days: int = 30
    customer_pool: int = 50_000

    # Traffic marginals (independent product -> uneven segment mix)
    p_bin: tuple = (0.35, 0.30, 0.20, 0.15)
    p_card: tuple = (0.60, 0.40)
    p_region: tuple = (0.50, 0.30, 0.20)
    p_amount: tuple = (0.60, 0.30, 0.10)
    p_recurring: float = 0.25
    amount_value: tuple = (20.0, 80.0, 300.0)  # simulated currency units, band centre

    # Approval logit
    base_logit: tuple = (1.62, 2.05, 1.88, 1.85)
    bin_effect: tuple = (0.10, 0.0, -0.20, 0.15)
    card_effect: tuple = (-0.10, 0.10)
    region_effect: tuple = (0.10, 0.0, -0.10)
    amount_effect: tuple = (0.10, 0.0, -0.30)
    recurring_effect: float = 0.20
    night_effect: float = -0.10  # hours 0..5

    # Drift (fractions of the run)
    drift_psp: int = 1
    drift_region: int = 1
    drift_at: float = 0.60
    drift_logit: float = -1.2
    recovery_at: float = 0.80
    recovery_logit: float = -0.6  # logit shift after partial recovery

    # Technical error process
    tech_base: float = 0.01
    tech_night_psp: int = 3
    tech_night_extra: float = 0.015  # hours 2..4
    incident_psp: int = 2
    incident_start: float = 0.35
    incident_end: float = 0.37
    incident_rate: float = 0.15

    # Economics (simulated currency units)
    fixed_fee: tuple = (0.20, 0.30, 0.25, 0.22)
    pct_fee: tuple = (0.015, 0.024, 0.019, 0.018)  # charged on approval only
    margin: tuple = (3.00, 12.00, 45.00)  # ~15% of ticket; see assumptions doc 3
    retry_cost: float = 0.05
    delay_abandon: float = 0.15  # non-recurring customers lost on a delayed retry

    # Decline model
    hard_share_nontech: float = 0.20 / 0.90
    soft_weights: tuple = (0.40, 0.20, 0.15, 0.15, 0.10)
    ambiguous_prob: tuple = (0.20, 0.35, 0.25)  # shown as ambiguous: hard, soft, tech
    degraded_prob_incident: float = 0.70
    degraded_prob_normal: float = 0.10

    # Retry success: cause -> (same_now, same_delayed, cascade_base, delay_seconds)
    retry_table: dict = field(default_factory=lambda: {
        0: (0.0, 0.0, 0.0, 0), 1: (0.0, 0.0, 0.0, 0),
        2: (0.0, 0.0, 0.0, 0), 3: (0.0, 0.0, 0.0, 0),
        4: (0.03, 0.30, 0.03, 86400),
        5: (0.25, 0.50, 0.35, 600),
        6: (0.02, 0.05, 0.05, 600),
        7: (0.05, 0.40, 0.10, 3600),
        8: (0.02, 0.03, 0.05, 600),
        9: (0.40, 0.55, 0.90, 600),
        10: (0.50, 0.60, 0.90, 600),
        11: (0.15, 0.40, 0.90, 600),
    })
    cascade_scaled: tuple = (5, 9, 10, 11)  # cascade success scales with target PSP health

    def to_dict(self) -> dict:
        return asdict(self)
