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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--baselines", action="store_true")
    ap.add_argument("--phase3", action="store_true", help="(done) frozen eval_seeds, run once")
    ap.add_argument("--phase3b", action="store_true", help="eval_seeds_v2, run once")
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--n", type=int, default=300_000)
    a = ap.parse_args()
    if a.phase3:
        return frozen_eval("phase3_eval_frozen", "eval_seeds")
    if a.phase3b:
        return frozen_eval("phase3b_eval_frozen_v2", "eval_seeds_v2")
    if a.baselines:
        return baselines(a.seeds, a.n)
    return smoke()


if __name__ == "__main__":
    raise SystemExit(main())
