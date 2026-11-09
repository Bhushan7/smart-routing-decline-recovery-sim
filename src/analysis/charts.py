"""Charts. Sized for readability at mobile width. All data simulated."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from ..simulator.config import SimConfig  # noqa: E402

COLORS = {"static": "#0072B2", "rule_based": "#E69F00", "oracle_routing": "#009E73",
          "oracle": "#000000", "adaptive": "#D55E00", "adaptive_v1": "#7F7F7F",
          "static_rules": "#56B4E9", "adaptive_rules": "#882255", "naive_retry": "#B2B2B2", "adaptive_agent": "#CC79A7"}
LABELS = {
    "static": "Static + failover", "rule_based": "Rule-based", "oracle_routing": "Oracle routing only",
    "oracle": "Oracle (routing + recovery)", "adaptive": "Adaptive router (failover only)",
    "adaptive_v1": "Adaptive (v1, 144-cell)", "adaptive_agent": "Adaptive + agent (stub)",
    "static_rules": "Static + rules recovery", "adaptive_rules": "Adaptive + rules recovery",
    "naive_retry": "Naive: retry everything",
}


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
    strategies = strategies or [s for s in ("rule_based", "adaptive_v1", "adaptive", "adaptive_agent", "oracle_routing")
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


def metric_panels(summary: pd.DataFrame, path, title: str, strategies=None) -> None:
    """Horizontal bars (mean, whiskers min-max) for the headline metrics, stacked for mobile width."""
    strategies = strategies or [s for s in summary.index]
    panels = [("auth_rate_final", "Final auth rate (%)", 100.0), ("net_value_per_txn", "Net value per txn", 1.0),
              ("soft_recovery_rate", "Soft-decline recovery rate (%)", 100.0),
              ("retry_efficiency", "Recoveries per retry", 1.0),
              ("wasted_retries_hard", "Retries on hard declines (per run)", 1.0)]
    fig, axes = plt.subplots(len(panels), 1, figsize=(7, 2.3 * len(panels)))
    for ax, (m, label, sc) in zip(axes, panels, strict=True):
        ys = range(len(strategies))
        mean = [summary.loc[s, f"{m}_mean"] * sc for s in strategies]
        lo = [summary.loc[s, f"{m}_min"] * sc for s in strategies]
        hi = [summary.loc[s, f"{m}_max"] * sc for s in strategies]
        ax.barh(list(ys), mean, color=[COLORS.get(s, "#444") for s in strategies], height=0.7)
        ax.errorbar(mean, list(ys), xerr=[[a - b for a, b in zip(mean, lo, strict=True)],
                                          [b - a for a, b in zip(mean, hi, strict=True)]],
                    fmt="none", ecolor="#222", capsize=2, lw=1)
        ax.set_yticks(list(ys))
        ax.set_yticklabels([LABELS.get(s, s) for s in strategies], fontsize=8)
        ax.invert_yaxis()
        ax.set_xlabel(label, fontsize=9)
        ax.grid(axis="x", alpha=0.25)
        if m in ("auth_rate_final", "net_value_per_txn"):
            lo_v = min(lo)
            ax.set_xlim(left=lo_v - (max(hi) - lo_v) * 0.6)
    axes[0].set_title(title, fontsize=11)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def guardrail_chart(seg: pd.DataFrame, path, title: str, pairs, thresh_pts: float = -0.5) -> None:
    """Per-segment final auth-rate change vs static (percentage points), sorted, mean over seeds."""
    piv = seg.pivot_table(index=["seed", "segment"], columns="strategy", values="auth_rate")
    fig, axes = plt.subplots(len(pairs), 1, figsize=(7, 3.2 * len(pairs)), sharey=True)
    for ax, (a, b) in zip(np_atleast(axes), pairs, strict=True):
        d = ((piv[a] - piv[b]) * 100).groupby("segment").mean().sort_values()
        colors = ["#D55E00" if v < thresh_pts else "#0072B2" for v in d.values]
        ax.bar(range(len(d)), d.values, color=colors, width=1.0)
        ax.axhline(thresh_pts, color="#D55E00", ls=":", lw=1)
        ax.axhline(0, color="#222", lw=0.8)
        ax.set_ylabel("Auth rate change (pts)", fontsize=9)
        ax.set_xticks([])
        ax.set_xlabel(f"144 segments, sorted. Worse than {thresh_pts} pts: {(d < thresh_pts).sum()}", fontsize=9)
        ax.set_title(f"{LABELS.get(a, a)} vs {LABELS.get(b, b)}", fontsize=10)
        ax.grid(axis="y", alpha=0.25)
    np_atleast(axes)[0].figure.suptitle(title, fontsize=11)
    fig = np_atleast(axes)[0].figure
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def np_atleast(axes):
    return axes if hasattr(axes, "__len__") else [axes]


def agent_cost_chart(cost: pd.DataFrame, path, title: str) -> None:
    """How ambiguous declines were handled, plus call volume. Stub LLM: tokens are estimates."""
    amb = cost.ambiguous.mean()
    calls, fb = cost.agent_calls.mean(), cost.fallbacks.mean()
    hits = (cost.cache_hit_rate_of_ambiguous * cost.ambiguous).mean()
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7, 5), gridspec_kw={"height_ratios": [1, 1.2]})
    left = 0
    for label, val, color in (("Agent called", calls, "#D55E00"), ("Served from cache", hits, "#0072B2"),
                              ("Fallback to rules", fb, "#999999")):
        ax1.barh([0], [val / amb * 100], left=left, color=color, label=f"{label}: {val / amb * 100:.1f}%")
        left += val / amb * 100
    ax1.set_xlim(0, 100)
    ax1.set_yticks([])
    ax1.set_xlabel("% of ambiguous declines (the only ones the agent can see)", fontsize=9)
    ax1.legend(fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.45), ncol=1)
    ax1.set_title(title, fontsize=11)
    stats = [("Agent calls per 1,000 declines", cost.calls_per_1000_declines.mean()),
             ("Tool calls per agent call", cost.tool_calls_per_agent_call.mean()),
             ("Est. input tokens per call", cost.input_tokens.mean() / max(1, calls)),
             ("Est. output tokens per call", cost.output_tokens.mean() / max(1, calls))]
    ax2.barh([s[0] for s in stats], [s[1] for s in stats], color="#444")
    for i, (_, v) in enumerate(stats):
        ax2.text(v, i, f" {v:,.1f}", va="center", fontsize=8)
    ax2.invert_yaxis()
    ax2.set_xscale("symlog")
    ax2.tick_params(labelsize=8)
    ax2.set_xlabel("Stub LLM: token counts are character-based estimates, latency not measured", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
