"""Metrics from Section 4.7 of the kickoff. All numbers come from simulated data."""
from __future__ import annotations

import numpy as np

from ..simulator.config import HARD_CAUSES, SOFT_CAUSES
from ..simulator.engine import SimResult
from ..simulator.world import World


def rolling_mean(x: np.ndarray, window: int) -> np.ndarray:
    c = np.cumsum(np.insert(x.astype(float), 0, 0.0))
    out = np.empty(len(x))
    for_idx = np.arange(len(x))
    lo = np.maximum(0, for_idx + 1 - window)
    out = (c[for_idx + 1] - c[lo]) / (for_idx + 1 - lo)
    return out


def summarize(res: SimResult) -> dict:
    n = res.n
    approvals = int(res.final_ok.sum())
    declined = res.cause >= 0
    soft = np.isin(res.cause, SOFT_CAUSES)
    hard = np.isin(res.cause, HARD_CAUSES)
    retries = int(res.retried.sum())
    recoveries = int(res.retry_ok.sum())
    return {
        "auth_rate_first": float(res.first_ok.mean()),
        "auth_rate_final": float(res.final_ok.mean()),
        "net_value_per_txn": float(res.value.mean()),
        "net_value_total": float(res.value.sum()),
        "net_cost_per_approval": float((res.fees.sum() + res.retry_cost.sum()) / max(1, approvals)),
        "retries": retries,
        "failed_retries": retries - recoveries,
        "recoveries": recoveries,
        "retry_efficiency": recoveries / retries if retries else float("nan"),
        "wasted_retries_hard": int((res.retried & hard).sum()),
        "soft_declines": int(soft.sum()),
        "soft_recovery_rate": float((res.retry_ok & soft).sum() / max(1, soft.sum())),
        "declines": int(declined.sum()),
        "n": n,
    }


def regret_curve(res: SimResult, oracle: SimResult) -> np.ndarray:
    """Cumulative net-value gap to the oracle on the same transaction stream."""
    return np.cumsum(oracle.value - res.value)


def adaptation_speed(
    res: SimResult, world: World, window: int = 2000, frac: float = 0.5, drift_free_from: float = 0.4,
) -> dict:
    """Region transactions after the drift event until the rolling share of traffic to the
    degraded PSP falls below `frac` x its pre-drift share (measured over [0.4, drift_at))."""
    c = world.cfg
    in_region = world.region[: res.n] == c.drift_region
    t = world.t_frac[: res.n]
    to_psp = (res.psp == c.drift_psp).astype(float)
    pre = in_region & (t >= drift_free_from) & (t < c.drift_at)
    pre_share = to_psp[pre].mean() if pre.any() else float("nan")
    out = {"pre_drift_share": float(pre_share), "txns_to_adapt": None, "status": "n/a"}
    if not pre_share or np.isnan(pre_share) or pre_share < 0.02:
        out["status"] = "psp_barely_used_pre_drift"
        return out
    post_idx = np.where(in_region & (t >= c.drift_at) & (t < c.recovery_at))[0]
    share = rolling_mean(to_psp[post_idx], window)
    below = np.where(share[window:] < frac * pre_share)[0]
    if len(below):
        out["txns_to_adapt"] = int(below[0] + window)
        out["status"] = "adapted"
    else:
        out["status"] = "never_reached"
    return out


def segment_guardrail(
    world: World, res: SimResult, base: SimResult, min_n: int = 200, thresh: float = -0.005
) -> list[dict]:
    """Segments whose final auth rate is worse than the baseline by more than |thresh|."""
    seg = world.segment[: res.n]
    flagged = []
    for s in np.unique(seg):
        m = seg == s
        if m.sum() < min_n:
            continue
        d = res.final_ok[m].mean() - base.final_ok[m].mean()
        if d < thresh:
            flagged.append({"segment": int(s), "n": int(m.sum()), "delta": float(d)})
    return flagged


def binned(res: SimResult, n_bins: int = 100) -> dict[str, np.ndarray]:
    k = res.n // n_bins
    cut = k * n_bins
    return {
        "auth_rate": res.final_ok[:cut].reshape(n_bins, k).mean(1),
        "net_value": res.value[:cut].reshape(n_bins, k).mean(1),
        "value_sum": res.value[:cut].reshape(n_bins, k).sum(1),
    }


def bootstrap_ci(values, n_boot: int = 10_000, seed: int = 0) -> tuple[float, float]:
    """95% percentile bootstrap interval of the mean across seeds."""
    v = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    means = rng.choice(v, size=(n_boot, len(v)), replace=True).mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))
