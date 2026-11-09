"""Eval entry point.

  python evals/run_evals.py --smoke      small run, stub LLM / no API key, used by CI
  python evals/run_evals.py --baselines  Phase 2 baseline comparison on DEV seeds (not frozen seeds)
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.analysis import charts, runner  # noqa: E402
from src.simulator.config import SimConfig  # noqa: E402

SEEDS = json.loads((ROOT / "evals" / "seeds.json").read_text())


def smoke() -> int:
    cfg = SimConfig(n_txn=20_000)
    _, res = runner.run_seed(cfg, SEEDS["dev_seeds"][0], ("adaptive_rules", "adaptive_agent", "oracle"))
    rep = res["adaptive_agent"].recovery.report()
    keys = ("declines", "ambiguous", "agent_calls", "fallbacks_total")
    print("[smoke] agent (stub LLM, no API key):", {k: rep[k] for k in keys})
    assert rep["agent_calls"] > 0 and rep["fallbacks_total"] == 0
    df = runner.run_many(cfg, SEEDS["dev_seeds"][:2], ROOT / "evals" / "results" / "_smoke")
    val = df.groupby("strategy").net_value_per_txn.mean()
    print(val.round(3).to_string())
    ok = val["oracle"] > val["static"] and val["oracle"] > val["rule_based"]
    print("[smoke] oracle beats baselines:", ok)
    return 0 if ok else 1


def baselines(n_seeds: int, n_txn: int) -> int:
    import pandas as pd

    cfg = SimConfig(n_txn=n_txn)
    out = ROOT / "evals" / "results" / "phase2_baselines_dev"
    df = runner.run_many(cfg, SEEDS["dev_seeds"][:n_seeds], out, seed_set="dev")
    agg = runner.aggregate(df)
    agg.round(4).to_csv(out / "summary.csv")
    ts = pd.read_csv(out / "timeseries.csv")
    charts.comparison_chart(ts, cfg, out / "baseline_comparison.png",
                            f"Baselines vs oracle, {n_seeds} dev seeds, {n_txn // 1000}k txns (simulated)")
    print(agg.round(4).T.to_string())
    return 0


def frozen_eval(out_name: str, seed_key: str) -> int:
    """Run all routers once on a FROZEN seed set. Refuses to overwrite earlier output."""
    import pandas as pd

    out = ROOT / "evals" / "results" / out_name
    if out.exists():
        print(f"{out} exists. Frozen eval seeds are run once; delete it deliberately to rerun.")
        return 1
    cfg = SimConfig()
    df = runner.run_many(cfg, SEEDS[seed_key], out, strategies=runner.ALL, seed_set="eval_frozen")
    agg = runner.aggregate(df)
    agg.round(4).to_csv(out / "summary.csv")
    piv = df.pivot(index="seed", columns="strategy", values="net_value_per_txn")
    pa = df.pivot(index="seed", columns="strategy", values="auth_rate_final")
    rows = []
    pairs = [("adaptive", "static"), ("adaptive", "rule_based"), ("rule_based", "static"),
             ("adaptive", "adaptive_v1"), ("adaptive_v1", "static")]
    for a, b in pairs:
        d = piv[a] - piv[b]
        da = (pa[a] - pa[b]) * 100
        rows.append({"comparison": f"{a} minus {b}", "net_value_diff_mean": d.mean(), "net_value_diff_min": d.min(),
                     "net_value_diff_max": d.max(), "seeds_a_better": int((d > 0).sum()), "n_seeds": len(d),
                     "auth_rate_diff_pts_mean": da.mean(), "auth_rate_diff_pts_min": da.min(),
                     "auth_rate_diff_pts_max": da.max()})
    pd.DataFrame(rows).round(4).to_csv(out / "paired_differences.csv", index=False)
    denom = piv["oracle_routing"] - piv["static"]
    gap = pd.DataFrame({"adaptive_v2": (piv["adaptive"] - piv["static"]) / denom,
                        "adaptive_v1": (piv["adaptive_v1"] - piv["static"]) / denom})
    gap.round(4).to_csv(out / "gap_captured.csv")
    ts = pd.read_csv(out / "timeseries.csv")
    n = f"{len(SEEDS[seed_key])} frozen seeds, 300k txns"
    charts.comparison_chart(ts, cfg, out / "router_comparison.png", f"All routers vs oracle\n{n} (simulated)")
    charts.adaptation_chart(ts, cfg, out / "adaptation_after_drift.png",
                            f"Traffic to PSP_B in REGION_2\n{n} (simulated)")
    print(agg.round(4).T.to_string())
    print(pd.DataFrame(rows).round(4).T.to_string())
    print("gap captured (mean, per seed):\n", gap.round(3).assign(seed=gap.index).to_string())
    print(gap.mean().round(3).to_dict())
    print(df.groupby("strategy")[["adapt_txns", "segments_worse_than_static"]].agg(["median", "min", "max"]))
    print(df.groupby("strategy").adapt_status.value_counts())
    return 0


def agent_dev(n_seeds: int, n_txn: int) -> int:
    """Phase 4 agent evaluation on DEV seeds (frozen seeds are reserved for Phase 5). Stub LLM, no API key."""
    import pandas as pd

    from src.analysis import agent_eval, metrics

    cfg = SimConfig(n_txn=n_txn)
    out = ROOT / "evals" / "results" / "phase4_agent_dev"
    out.mkdir(parents=True, exist_ok=True)
    seeds = SEEDS["dev_seeds"][2:2 + n_seeds]
    rows, dq_rows, cost_rows, labeled = [], [], [], []
    for seed in seeds:
        world, res = runner.run_seed(cfg, seed, runner.AGENT_STRATEGIES)
        oracle = res["oracle"]
        for name, r in res.items():
            rows.append({"seed": seed, "strategy": name, **metrics.summarize(r),
                         "final_regret_vs_oracle": float(metrics.regret_curve(r, oracle)[-1]),
                         "segments_worse_than_static": len(metrics.segment_guardrail(world, r, res["static"]))
                         if name != "static" else 0})
        for sname in ("adaptive_agent_v1", "adaptive_agent"):
            lab = agent_eval.labeled_set(world, res[sname])
            lab.insert(0, "seed", seed)
            lab.insert(1, "strategy", sname)
            labeled.append(lab)
            dq_rows.append({"seed": seed, "strategy": sname, **agent_eval.decision_quality(lab)})
            cost_rows.append({"seed": seed, "strategy": sname, **agent_eval.agent_cost(res[sname])})
        print("seed", seed, "done", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(out / "per_seed.csv", index=False)
    cols = ["auth_rate_final", "net_value_per_txn", "net_cost_per_approval", "retry_efficiency", "wasted_retries_hard",
            "soft_recovery_rate", "final_regret_vs_oracle", "segments_worse_than_static"]
    g = df.groupby("strategy")[cols]
    agg = g.mean().add_suffix("_mean").join(g.min().add_suffix("_min")).join(g.max().add_suffix("_max"))
    agg = agg.reindex([x for x in runner.AGENT_STRATEGIES if x in agg.index])
    agg.round(4).to_csv(out / "summary.csv")
    piv = df.pivot(index="seed", columns="strategy", values="net_value_per_txn")
    pa = df.pivot(index="seed", columns="strategy", values="auth_rate_final")
    paired = []
    for a, b in (("adaptive_agent", "adaptive_rules"), ("adaptive_agent_v1", "adaptive_rules"),
                 ("adaptive_rules", "adaptive"), ("adaptive_agent", "adaptive"), ("adaptive_rules", "static_rules"),
                 ("static_rules", "static"), ("adaptive_agent", "static")):
        d, da = piv[a] - piv[b], (pa[a] - pa[b]) * 100
        paired.append({"comparison": f"{a} minus {b}", "net_value_diff_mean": d.mean(), "min": d.min(), "max": d.max(),
                       "seeds_a_better": int((d > 0).sum()), "n_seeds": len(d), "auth_pts_mean": da.mean()})
    pd.DataFrame(paired).round(4).to_csv(out / "ablation_paired.csv", index=False)
    dq = pd.DataFrame(dq_rows).drop(columns=["exact_match_by_true_class"]).round(4)
    dq.to_csv(out / "decision_quality.csv", index=False)
    pd.DataFrame(cost_rows).drop(columns=["fallback_detail"]).round(4).to_csv(out / "agent_cost.csv", index=False)
    lab_all = pd.concat(labeled)
    first = lab_all[(lab_all.seed == seeds[0]) & (lab_all.strategy == "adaptive_agent")]
    first.to_csv(out / "labeled_ambiguous_declines_seed1.csv", index=False)
    pooled = {}
    for sname in ("adaptive_agent_v1", "adaptive_agent"):
        sub = lab_all[lab_all.strategy == sname]
        pooled[sname] = agent_eval.decision_quality(sub)
        agent_eval.failure_cases(sub).to_csv(out / f"failure_cases_{sname}.csv", index=False)
    fail = agent_eval.failure_cases(lab_all[lab_all.strategy == "adaptive_agent_v1"])
    (out / "decision_quality_pooled.json").write_text(json.dumps(pooled, indent=1, default=float))
    print(agg[[c for c in agg.columns if c.endswith("_mean")]].round(4).T.to_string())
    print(pd.DataFrame(paired).round(4).T.to_string())
    print(json.dumps(pooled, indent=1, default=float))
    print(pd.DataFrame(cost_rows).drop(columns=["fallback_detail"]).groupby("strategy").mean(numeric_only=True)
          .round(3).T.to_string())
    print(fail[["true_cause", "code", "agent_action", "oracle_action", "value_gap_agent", "explanation"]].to_string())
    return 0


def phase5_charts(out, cfg, n_seeds: int) -> None:
    """Redraw the final charts from SAVED results (no simulation)."""
    import pandas as pd

    from src.analysis import summary as sm

    summ = pd.read_csv(out / "summary.csv").set_index("strategy")
    n = f"{n_seeds} frozen seeds, 300k txns"
    ts = pd.read_csv(out / "timeseries.csv")
    seg = pd.read_csv(out / "segment_auth.csv")
    cost = pd.read_csv(out / "agent_cost.csv")
    main_set = ["static", "rule_based", "adaptive", "adaptive_agent", "oracle_routing", "oracle"]
    charts.comparison_chart(ts, cfg, out / "router_comparison.png", f"All routers vs oracle\n{n} (simulated)", main_set)
    charts.adaptation_chart(ts, cfg, out / "adaptation_after_drift.png",
                            f"Traffic to PSP_B in REGION_2\n{n} (simulated)",
                            ["rule_based", "adaptive", "oracle_routing"])
    charts.metric_panels(summ, out / "router_metrics.png", f"Headline metrics by strategy\n{n} (simulated)",
                         [s for s in sm.ORDER if s in summ.index])
    charts.guardrail_chart(seg, out / "segment_guardrail.png", f"Per-segment auth rate vs static\n{n} (simulated)",
                           [("adaptive", "static"), ("adaptive_agent", "static")])
    charts.agent_cost_chart(cost, out / "agent_cost.png", "Agent usage (stub LLM, simulated)")


def phase5_final() -> int:
    """Final evaluation: all strategies on FROZEN eval_seeds_v2, run once. Refuses to overwrite."""
    import pandas as pd

    from src.analysis import summary as sm

    out = ROOT / "evals" / "results" / "phase5_final_eval"
    if out.exists():
        print(f"{out} exists. Frozen seeds are run once; delete it deliberately to rerun.")
        return 1
    cfg = SimConfig()
    seeds = SEEDS["eval_seeds_v2"]
    runner.run_final(cfg, seeds, out, seed_set="eval_seeds_v2 (frozen)")
    df = pd.read_csv(out / "per_seed.csv")
    summ = sm.summary_table(df)
    summ.round(5).to_csv(out / "summary.csv")
    paired = pd.concat([sm.paired(df, sm.PAIRS, "net_value_per_txn"),
                        sm.paired(df, sm.PAIRS, "auth_rate_final", 100.0),
                        sm.paired(df, sm.PAIRS, "soft_recovery_rate", 100.0)])
    paired.round(5).to_csv(out / "paired_differences.csv", index=False)
    hl = sm.headline(df)
    (out / "headline.json").write_text(json.dumps(hl, indent=1))
    phase5_charts(out, cfg, len(seeds))
    print(json.dumps(hl, indent=1))
    show = ["auth_rate_final_mean", "net_value_per_txn_mean", "soft_recovery_rate_mean", "retry_efficiency_mean",
            "failed_retries_mean", "wasted_retries_hard_mean", "final_regret_vs_oracle_mean",
            "segments_worse_than_static_mean", "adapt_txns_median"]
    print(summ[show].round(4).T.to_string())
    print(paired[paired.metric == "net_value_per_txn"].round(4).to_string())
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--baselines", action="store_true")
    ap.add_argument("--phase3", action="store_true", help="(done) frozen eval_seeds, run once")
    ap.add_argument("--phase3b", action="store_true", help="eval_seeds_v2, run once")
    ap.add_argument("--charts-only", action="store_true", help="redraw phase 5 charts from saved results")
    ap.add_argument("--phase5", action="store_true", help="final eval on eval_seeds_v2, run once")
    ap.add_argument("--agent", action="store_true", help="Phase 4 agent eval on dev seeds (stub LLM)")
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--n", type=int, default=300_000)
    a = ap.parse_args()
    if a.charts_only:
        out = ROOT / "evals" / "results" / "phase5_final_eval"
        phase5_charts(out, SimConfig(), len(json.loads((out / "run_info.json").read_text())["seeds"]))
        return 0
    if a.phase5:
        return phase5_final()
    if a.agent:
        return agent_dev(a.seeds, a.n)
    if a.phase3:
        return frozen_eval("phase3_eval_frozen", "eval_seeds")
    if a.phase3b:
        return frozen_eval("phase3b_eval_frozen_v2", "eval_seeds_v2")
    if a.baselines:
        return baselines(a.seeds, a.n)
    return smoke()


if __name__ == "__main__":
    raise SystemExit(main())
