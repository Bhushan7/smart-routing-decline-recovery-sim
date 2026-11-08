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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--baselines", action="store_true")
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--n", type=int, default=300_000)
    a = ap.parse_args()
    if a.baselines:
        return baselines(a.seeds, a.n)
    return smoke()


if __name__ == "__main__":
    raise SystemExit(main())
