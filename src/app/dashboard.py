"""Streamlit dashboard. Reads SAVED results only (no simulation runs here). All numbers are simulated.

Run: make demo   (or: streamlit run src/app/dashboard.py)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.simulator.config import AMOUNT_BANDS, BIN_GROUPS, CARD_TYPES, REGIONS  # noqa: E402

RESULTS = Path(os.environ.get("RESULTS_DIR", ROOT / "evals" / "results" / "phase5_final_eval"))
LABELS = {
    "static": "Static + failover", "rule_based": "Rule-based", "naive_retry": "Naive: retry everything",
    "static_rules": "Static + rules recovery", "adaptive": "Adaptive (failover only)",
    "adaptive_rules": "Adaptive + rules recovery", "adaptive_agent": "Adaptive + agent (stub LLM)",
    "oracle_routing": "Oracle routing only", "oracle": "Oracle (routing + recovery)",
}
ORDER = list(LABELS)
COLORS = {"static": "#0072B2", "rule_based": "#E69F00", "naive_retry": "#B2B2B2", "static_rules": "#56B4E9",
          "adaptive": "#D55E00", "adaptive_rules": "#882255", "adaptive_agent": "#CC79A7", "oracle_routing": "#009E73",
          "oracle": "#000000"}

st.set_page_config(page_title="Routing and decline recovery (simulated)", layout="wide")


@st.cache_data
def load(name: str) -> pd.DataFrame:
    return pd.read_csv(RESULTS / name)


@st.cache_data
def load_json(name: str) -> dict:
    return json.loads((RESULTS / name).read_text())


def pct(x, d=2):
    return f"{x:.{d}f}"


if not (RESULTS / "per_seed.csv").exists():
    st.error(f"No saved results in {RESULTS}. Run `python evals/run_evals.py --phase5` first.")
    st.stop()

info, summ, hl = load_json("run_info.json"), load("summary.csv").set_index("strategy"), load_json("headline.json")
st.title("Smart routing and decline recovery")
st.warning(
    "All numbers are **simulated** (synthetic data, simplified decline model). The agent shown here is a "
    "**deterministic stub LLM, not Claude**: it exercises the pipeline and gives a heuristic baseline only. "
    f"Results: {info['seed_set']}, {len(info['seeds'])} seeds, 300k transactions each. Spread = min to max across seeds."
)
tab1, tab2, tab3, tab4 = st.tabs(["Router comparison", "Drift timeline", "Segment drill-down", "Agent decisions"])

with tab1:
    c = st.columns(4)
    a, sr, n, g = (hl["auth_rate_gain_pts_vs_static"], hl["soft_decline_recovery_rate_agent"],
                   hl["net_value_gain_pct_vs_static"], hl["agent_minus_rules_only_net_value"])
    c[0].metric("Auth rate vs static", f"+{a['mean']:.2f} pts", help="Adaptive + agent (stub) minus static, paired over seeds")
    c[1].metric("Soft declines recovered", f"{sr['mean'] * 100:.1f}%", help="Static recovers 0%: it never retries soft declines")
    c[2].metric("Net value vs static", f"+{n['mean']:.2f}%", help="Net value per transaction, paired over seeds")
    c[3].metric("Agent minus rules-only", f"{g['mean']:+.3f}", help="Net value per transaction; negative means the stub agent is worse")
    c[0].caption(f"95% CI {a['ci95'][0]:.2f} to {a['ci95'][1]:.2f}")
    c[1].caption(f"95% CI {sr['ci95'][0] * 100:.1f}% to {sr['ci95'][1] * 100:.1f}%")
    c[2].caption(f"95% CI {n['ci95'][0]:.2f}% to {n['ci95'][1]:.2f}%")
    c[3].caption(f"95% CI {g['ci95'][0]:+.3f} to {g['ci95'][1]:+.3f}")
    st.caption("The agent adds no measurable value over deterministic rules in this simulation (stub LLM). "
               "Most of the gain comes from decline-recovery rules.")
    metric_names = {
        "auth_rate_final": ("Final auth rate (%)", 100), "net_value_per_txn": ("Net value per txn", 1),
        "soft_recovery_rate": ("Soft-decline recovery (%)", 100), "retry_efficiency": ("Recoveries per retry", 1),
        "failed_retries": ("Failed retries per run", 1), "wasted_retries_hard": ("Retries on hard declines per run", 1),
        "final_regret_vs_oracle": ("Regret vs oracle", 1), "segments_worse_than_static": ("Segments worse than static", 1),
    }
    metric = st.selectbox("Metric", list(metric_names), format_func=lambda m: metric_names[m][0])
    label, sc = metric_names[metric]
    d = pd.DataFrame({
        "Strategy": [LABELS[x] for x in ORDER if x in summ.index],
        "Mean": [summ.loc[x, f"{metric}_mean"] * sc for x in ORDER if x in summ.index],
        "Min": [summ.loc[x, f"{metric}_min"] * sc for x in ORDER if x in summ.index],
        "Max": [summ.loc[x, f"{metric}_max"] * sc for x in ORDER if x in summ.index],
    })
    d["Key"] = [x for x in ORDER if x in summ.index]
    zero = metric in ("final_regret_vs_oracle", "failed_retries", "wasted_retries_hard", "segments_worse_than_static",
                      "soft_recovery_rate", "retry_efficiency")
    base = alt.Chart(d).encode(y=alt.Y("Strategy:N", sort=None, title=None))
    span = d.Max.max() - d.Min.min()
    dom = alt.Undefined if zero else [float(d.Min.min() - 0.6 * span), float(d.Max.max() + 0.1 * span)]
    bars = base.mark_bar(clip=True).encode(
        x=alt.X("Mean:Q", title=label, scale=alt.Scale(zero=zero, domain=dom)),
        color=alt.Color("Key:N", scale=alt.Scale(domain=list(COLORS), range=list(COLORS.values())), legend=None))
    st.altair_chart(bars + base.mark_rule(color="#222").encode(x="Min:Q", x2="Max:Q"), use_container_width=True)
    if not zero:
        st.caption("Axis does not start at zero so differences are visible. Whiskers: min to max across seeds.")
    st.dataframe(d.drop(columns="Key").round(4), hide_index=True, use_container_width=True)
    st.subheader("Paired differences across seeds")
    pdf = load("paired_differences.csv")
    pm = st.selectbox("Paired metric", ["net_value_per_txn", "auth_rate_final", "soft_recovery_rate"],
                      format_func=lambda m: {"net_value_per_txn": "Net value per txn",
                                             "auth_rate_final": "Auth rate (points)",
                                             "soft_recovery_rate": "Soft recovery (points)"}[m])
    st.dataframe(pdf[pdf.metric == pm].drop(columns="metric").round(4), hide_index=True, use_container_width=True)
    for f, cap in (("router_comparison.png", "Auth rate, net value and regret over time"),
                   ("router_metrics.png", "Headline metrics by strategy")):
        if (RESULTS / f).exists():
            st.image(str(RESULTS / f), caption=cap + " (simulated)")

with tab2:
    ts = load("timeseries.csv")
    cfg = info["config"]
    opts = {"auth_rate": "Final auth rate", "net_value": "Net value per txn", "cum_regret": "Cumulative regret vs oracle",
            "drift_psp_share_in_region": "Share of REGION_2 traffic sent to PSP_B"}
    m = st.selectbox("Metric", list(opts), format_func=lambda k: opts[k], key="ts_metric")
    strat = st.multiselect("Strategies", [x for x in ORDER if x in set(ts.strategy)],
                           default=[x for x in ("static", "rule_based", "adaptive", "adaptive_agent", "oracle") if x in set(ts.strategy)],
                           format_func=lambda x: LABELS[x])
    sub = ts[ts.strategy.isin(strat)].groupby(["strategy", "t_frac"])[m].mean().reset_index()
    sub["Strategy"] = sub.strategy.map(LABELS)
    sub["Key"] = sub.strategy
    line = alt.Chart(sub).mark_line().encode(
        x=alt.X("t_frac:Q", title="Share of run"), y=alt.Y(f"{m}:Q", title=opts[m], scale=alt.Scale(zero=False)),
        color=alt.Color("Strategy:N", legend=alt.Legend(orient="bottom"),
                        scale=alt.Scale(domain=[LABELS[k] for k in COLORS], range=list(COLORS.values()))))
    rules = alt.Chart(pd.DataFrame({"x": [cfg["drift_at"], cfg["recovery_at"]], "e": ["PSP_B degrades", "Partial recovery"]})
                      ).mark_rule(strokeDash=[4, 3]).encode(x="x:Q", color=alt.value("#b00020"))
    band = alt.Chart(pd.DataFrame({"a": [cfg["incident_start"]], "b": [cfg["incident_end"]]})
                     ).mark_rect(opacity=0.15, color="#888").encode(x="a:Q", x2="b:Q")
    st.altair_chart(band + line + rules, use_container_width=True)
    st.caption(f"Dotted lines: PSP_B degrades in REGION_2 at {cfg['drift_at']:.0%} of the run and partly recovers at "
               f"{cfg['recovery_at']:.0%}. Grey band: PSP_C incident. Mean across {len(info['seeds'])} seeds (simulated).")
    if (RESULTS / "adaptation_after_drift.png").exists():
        st.image(str(RESULTS / "adaptation_after_drift.png"))
    ad = pd.read_csv(RESULTS / "per_seed.csv")
    ad = ad[ad.strategy.isin(["adaptive", "adaptive_rules", "adaptive_agent", "oracle_routing"])]
    st.write("**Adaptation speed**: region transactions after the drift until traffic to the degraded PSP falls "
             "below 50% of its pre-drift share.")
    st.dataframe(ad.groupby("strategy").adapt_txns.agg(["median", "min", "max", "count"]).rename(
        index=LABELS), use_container_width=True)

with tab3:
    seg = load("segment_auth.csv")
    c = st.columns(5)
    pick = [c[0].selectbox("BIN group", ["All"] + list(BIN_GROUPS)), c[1].selectbox("Card", ["All"] + list(CARD_TYPES)),
            c[2].selectbox("Region", ["All"] + list(REGIONS)), c[3].selectbox("Amount", ["All"] + list(AMOUNT_BANDS)),
            c[4].selectbox("Recurring", ["All", "recurring", "one-time"])]
    rest, rec = divmod(seg.segment, 2)
    rest, am = divmod(rest, 3)
    rest, rg = divmod(rest, 3)
    bn, cd = divmod(rest, 2)
    mask = pd.Series(True, index=seg.index)
    for p, col, names in ((pick[0], bn, BIN_GROUPS), (pick[1], cd, CARD_TYPES), (pick[2], rg, REGIONS),
                          (pick[3], am, AMOUNT_BANDS)):
        if p != "All":
            mask &= col == list(names).index(p)
    if pick[4] != "All":
        mask &= rec == (1 if pick[4] == "recurring" else 0)
    sel = seg[mask].copy()
    sel["ok"] = sel.auth_rate * sel.n
    g = sel.groupby("strategy")[["ok", "n"]].sum()
    out = (g.ok / g.n * 100).rename("Auth rate (%)").to_frame()
    out["Delta vs static (pts)"] = out["Auth rate (%)"] - out.loc["static", "Auth rate (%)"]
    out = out.reindex([x for x in ORDER if x in out.index])
    out.index = [LABELS[x] for x in out.index]
    st.write(f"**{sel.segment.nunique()} segment(s)**, {int(g.n.max() / len(info['seeds'])):,} txns per run on average")
    st.dataframe(out.round(3), use_container_width=True)
    st.bar_chart(out["Delta vs static (pts)"])
    st.subheader("Segment guardrail")
    st.caption("Segments whose auth rate is worse than static by more than 0.5 points (min 200 txns). "
               "The average can improve while a segment gets worse; this view exposes it.")
    gd = load("segment_guardrail.csv")
    cnt = gd.groupby(["strategy", "seed"]).size().unstack(fill_value=0).mean(axis=1).rename("Avg segments worse")
    cnt = cnt.reindex([x for x in ORDER if x in cnt.index]).rename(index=LABELS)
    st.dataframe(cnt.round(1), use_container_width=True)
    if (RESULTS / "segment_guardrail.png").exists():
        st.image(str(RESULTS / "segment_guardrail.png"))

with tab4:
    ex = load("agent_decision_examples.csv")
    dq, cost = load("agent_decision_quality.csv"), load("agent_cost.csv")
    c = st.columns(4)
    c[0].metric("Exact match with oracle", f"{dq.exact_match_rate.mean() * 100:.1f}%")
    c[1].metric("Share of oracle value (ambiguous declines)", f"{dq.share_of_oracle_value_agent.mean() * 100:.1f}%",
                f"rules default: {dq.share_of_oracle_value_rules_default.mean() * 100:.1f}%", delta_color="off")
    c[2].metric("Agent calls per 1,000 declines", f"{cost.calls_per_1000_declines.mean():.1f}")
    c[3].metric("Fallbacks per run", f"{cost.fallbacks.mean():.1f}")
    st.caption("Stub LLM: exact tokens and latency are not measured. A rules default of 'delayed retry' already "
               "captures most of the available value, which caps what any agent can add here.")
    f1, f2, f3 = st.columns(3)
    cls = f1.multiselect("True cause class (hidden)", sorted(ex.true_class.unique()), default=sorted(ex.true_class.unique()))
    mt = f2.selectbox("Match with oracle", ["All", "Matches", "Does not match"])
    code = f3.multiselect("Response code", sorted(ex.code.unique()), default=sorted(ex.code.unique()))
    v = ex[ex.true_class.isin(cls) & ex.code.isin(code)]
    if mt != "All":
        v = v[v.exact_match == (mt == "Matches")]
    cols = ["seed", "idx", "code", "psp", "true_cause", "agent_action", "agent_target", "oracle_action", "oracle_target",
            "value_gap_agent", "agent_confidence", "explanation"]
    st.write(f"{len(v):,} sampled ambiguous declines")
    st.dataframe(v.sort_values("value_gap_agent", ascending=False)[cols].round(3), hide_index=True,
                 use_container_width=True, height=420)
    if (RESULTS / "agent_cost.png").exists():
        st.image(str(RESULTS / "agent_cost.png"))
