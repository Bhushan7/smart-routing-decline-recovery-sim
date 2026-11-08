"""Grid search for adaptive-router parameters. DEV SEEDS ONLY (never the frozen eval seeds).

Run: python evals/tune_adaptive.py
"""
import itertools
import json
import sys
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.analysis import metrics  # noqa: E402
from src.routers.adaptive import AdaptiveParams, AdaptiveRouter  # noqa: E402
from src.routers.recovery import FailoverRecovery  # noqa: E402
from src.simulator.config import SimConfig  # noqa: E402
from src.simulator.engine import run  # noqa: E402
from src.simulator.world import World  # noqa: E402

SEEDS = json.loads((ROOT / "evals" / "seeds.json").read_text())
TUNE_SEEDS = SEEDS["dev_seeds"][5:8]       # 1005-1007: tuning
HOLDOUT_SEEDS = SEEDS["dev_seeds"][10:13]  # 1010-1012: dev hold-out check of the chosen setting
GRID = {"decay": [1.0, 0.999, 0.995], "prior_strength": [5.0, 20.0, 60.0], "explore_floor": [0.01, 0.03]}
CFG = SimConfig()


def one(args):
    params, seed = args
    world = World(CFG, seed)
    rng = np.random.default_rng(np.random.SeedSequence([seed, 77]))
    res = run(world, AdaptiveRouter(CFG, rng, AdaptiveParams(**params)), FailoverRecovery(0, 2))
    ad = metrics.adaptation_speed(res, world)
    return {**params, "seed": seed, "net_value_per_txn": res.value.mean(), "auth_rate_final": res.final_ok.mean(),
            "adapt_txns": ad["txns_to_adapt"]}


def main():
    out = ROOT / "evals" / "results" / "phase3_tuning_dev"
    out.mkdir(parents=True, exist_ok=True)
    keys = list(GRID)
    combos = [dict(zip(keys, v, strict=True)) for v in itertools.product(*GRID.values())]
    tasks = [(c, s) for c in combos for s in TUNE_SEEDS]
    with Pool(4) as pool:
        rows = pool.map(one, tasks)
    df = pd.DataFrame(rows)
    df.to_csv(out / "tuning_runs.csv", index=False)
    agg = df.groupby(keys).agg(net_value=("net_value_per_txn", "mean"), auth=("auth_rate_final", "mean"),
                               adapt=("adapt_txns", "mean")).sort_values("net_value", ascending=False)
    agg.round(4).to_csv(out / "tuning_summary.csv")
    print(agg.round(4).to_string())


if __name__ == "__main__":
    main()
