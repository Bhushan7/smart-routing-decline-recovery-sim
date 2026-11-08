"""Charts. Sized for readability at mobile width. All data simulated."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from ..simulator.config import SimConfig  # noqa: E402

COLORS = {"static": "#0072B2", "rule_based": "#E69F00", "oracle_routing": "#009E73",
          "oracle": "#000000", "adaptive": "#D55E00", "adaptive_agent": "#CC79A7"}
LABELS = {"static": "Static + failover", "rule_based": "Rule-based", "oracle_routing": "Oracle routing only",
          "oracle": "Oracle (routing + recovery)", "adaptive": "Adaptive", "adaptive_agent": "Adaptive + agent"}


def _mark(ax, cfg: SimConfig):
    ax.axvspan(cfg.incident_start, cfg.incident_end, color="#bbbbbb", alpha=0.5, lw=0)
    ax.axvline(cfg.drift_at, color="#b00020", ls=":", lw=1.5)
    ax.axvline(cfg.recovery_at, color="#2e7d32", ls=":", lw=1.5)


def comparison_chart(ts: pd.DataFrame, cfg: SimConfig, path, title: str, strategies=None) -> None:
    strategies = strategies or [s for s in COLORS if s in set(ts.strategy)]
    fig, axes = plt.subplots(3, 1, figsize=(7, 10), sharex=True)
    panels = [("auth_rate", "Final auth rate % (simulated)", 100),
              ("net_value", "Net value per txn (simulated units)", 1),
              ("cum_regret", "Cumulative regret vs oracle (simulated units)", 1)]
    for ax, (col, ylabel, scale) in zip(axes, panels, strict=True):
        for s in strategies:
            if col == "cum_regret" and s == "oracle":
                continue
            d = ts[ts.strategy == s].groupby("t_frac")[col].agg(["mean", "min", "max"])
            ls = "--" if s.startswith("oracle") else "-"
            ax.plot(d.index, d["mean"] * scale, color=COLORS[s], ls=ls, lw=2, label=LABELS[s])
            ax.fill_between(d.index, d["min"] * scale, d["max"] * scale, color=COLORS[s], alpha=0.12, lw=0)
        _mark(ax, cfg)
        ax.set_ylabel(ylabel, fontsize=10)
        ax.grid(alpha=0.25)
    axes[0].legend(fontsize=9, loc="lower left")
    axes[0].set_title(title, fontsize=12)
    axes[-1].set_xlabel("Share of run (red: PSP_B degrades in REGION_2; green: partial recovery; grey: incident)",
                        fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def adaptation_chart(ts: pd.DataFrame, cfg: SimConfig, path, title: str, strategies=None) -> None:
    """Share of affected-region traffic sent to the degraded PSP over time."""
    strategies = strategies or [s for s in ("rule_based", "adaptive", "adaptive_agent", "oracle_routing")
                                if s in set(ts.strategy)]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for s in strategies:
        d = ts[ts.strategy == s].groupby("t_frac")["drift_psp_share_in_region"].agg(["mean", "min", "max"])
        ls = "--" if s.startswith("oracle") else "-"
        ax.plot(d.index, d["mean"] * 100, color=COLORS[s], ls=ls, lw=2, label=LABELS[s])
        ax.fill_between(d.index, d["min"] * 100, d["max"] * 100, color=COLORS[s], alpha=0.12, lw=0)
    _mark(ax, cfg)
    ax.set_ylabel("% of REGION_2 traffic sent to PSP_B", fontsize=10)
    ax.set_xlabel("Share of run (red: PSP_B degrades; green: partial recovery)", fontsize=9)
    ax.set_title(title, fontsize=11)
    ax.legend(fontsize=9)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
