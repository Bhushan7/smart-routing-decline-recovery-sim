"""Aggregate per-seed results into mean, spread and paired differences. All numbers simulated."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .metrics import bootstrap_ci

METRICS = ["auth_rate_final", "auth_rate_first", "net_value_per_txn", "net_cost_per_approval", "retry_efficiency",
           "soft_recovery_rate", "failed_retries", "wasted_retries_hard", "final_regret_vs_oracle",
           "segments_worse_than_static"]
ORDER = ["static", "rule_based", "naive_retry", "static_rules", "adaptive", "adaptive_rules", "adaptive_agent",
         "oracle_routing", "oracle"]


def summary_table(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for strat, g in df.groupby("strategy"):
        row = {"strategy": strat, "n_seeds": g.seed.nunique()}
        for m in METRICS:
            v = g[m].astype(float).to_numpy()
            lo, hi = bootstrap_ci(v)
            row.update({f"{m}_mean": v.mean(), f"{m}_min": v.min(), f"{m}_max": v.max(),
                        f"{m}_ci_lo": lo, f"{m}_ci_hi": hi})
        ad = g.adapt_txns.dropna()
        row["adapt_txns_median"] = float(ad.median()) if len(ad) else np.nan
        row["adapt_reached_seeds"] = int(len(ad))
        rows.append(row)
    t = pd.DataFrame(rows).set_index("strategy")
    return t.reindex([s for s in ORDER if s in t.index])


def paired(df: pd.DataFrame, pairs, metric: str = "net_value_per_txn", scale: float = 1.0) -> pd.DataFrame:
    piv = df.pivot(index="seed", columns="strategy", values=metric)
    rows = []
    for a, b in pairs:
        d = (piv[a] - piv[b]) * scale
        lo, hi = bootstrap_ci(d.to_numpy())
        rows.append({"comparison": f"{a} minus {b}", "metric": metric, "mean_diff": d.mean(), "min": d.min(),
                     "max": d.max(), "ci_lo": lo, "ci_hi": hi, "seeds_a_better": int((d > 0).sum()),
                     "n_seeds": len(d)})
    return pd.DataFrame(rows)


PAIRS = [("adaptive_agent", "static"), ("adaptive_agent", "rule_based"), ("adaptive", "static"),
         ("adaptive_rules", "adaptive"), ("static_rules", "static"), ("adaptive_rules", "static_rules"),
         ("adaptive_agent", "adaptive_rules"), ("adaptive_agent", "adaptive")]


def headline(df: pd.DataFrame) -> dict:
    piv = lambda m: df.pivot(index="seed", columns="strategy", values=m)  # noqa: E731
    auth, nv, soft = piv("auth_rate_final"), piv("net_value_per_txn"), piv("soft_recovery_rate")
    failed, hard = piv("failed_retries"), piv("wasted_retries_hard")
    eff, regret = piv("retry_efficiency"), piv("final_regret_vs_oracle")

    def mean_ci(x):
        lo, hi = bootstrap_ci(x.to_numpy())
        return {"mean": float(x.mean()), "ci95": [lo, hi], "min": float(x.min()), "max": float(x.max())}

    cut = 1 - failed["adaptive_agent"] / failed["naive_retry"]
    cut_hard = 1 - hard["adaptive_agent"] / hard["naive_retry"]
    return {
        "n_seeds": int(len(auth)),
        "auth_rate_gain_pts_vs_static": mean_ci((auth["adaptive_agent"] - auth["static"]) * 100),
        "auth_rate_gain_pts_vs_rule_based": mean_ci((auth["adaptive_agent"] - auth["rule_based"]) * 100),
        "soft_decline_recovery_rate_agent": mean_ci(soft["adaptive_agent"]),
        "soft_decline_recovery_rate_static": mean_ci(soft["static"]),
        "failed_retries_cut_vs_naive_retry_all": mean_ci(cut),
        "hard_decline_retries_cut_vs_naive_retry_all": mean_ci(cut_hard),
        "hard_decline_retries_agent_per_run": mean_ci(hard["adaptive_agent"]),
        "hard_decline_retries_static_per_run": mean_ci(hard["static"]),
        "retry_efficiency_agent": mean_ci(eff["adaptive_agent"]),
        "retry_efficiency_naive": mean_ci(eff["naive_retry"]),
        "net_value_gain_pct_vs_static": mean_ci((nv["adaptive_agent"] / nv["static"] - 1) * 100),
        "net_value_gain_pct_vs_rule_based": mean_ci((nv["adaptive_agent"] / nv["rule_based"] - 1) * 100),
        "share_of_oracle_net_value_agent": mean_ci(nv["adaptive_agent"] / nv["oracle"]),
        "share_of_oracle_net_value_static": mean_ci(nv["static"] / nv["oracle"]),
        "regret_cut_vs_static_pct": mean_ci((1 - regret["adaptive_agent"] / regret["static"]) * 100),
        "agent_minus_rules_only_net_value": mean_ci(nv["adaptive_agent"] - nv["adaptive_rules"]),
        "recovery_rules_minus_failover_net_value": mean_ci(nv["adaptive_rules"] - nv["adaptive"]),
        "routing_contribution_on_top_of_recovery": mean_ci(nv["adaptive_rules"] - nv["static_rules"]),
    }
