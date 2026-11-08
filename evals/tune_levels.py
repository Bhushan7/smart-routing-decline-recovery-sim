"""Compare router learning hierarchies (Phase 3b). DEV SEEDS ONLY.

Run: python evals/tune_levels.py
"""
import json
import sys
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.analysis import metrics  # noqa: E402
from src.routers.adaptive import FULL, AdaptiveParams, AdaptiveRouter  # noqa: E402
from src.routers.recovery import FailoverRecovery  # noqa: E402
from src.simulator.config import SimConfig  # noqa: E402
from src.simulator.engine import run  # noqa: E402
from src.simulator.world import World  # noqa: E402

SEEDS = json.loads((ROOT / "evals" / "seeds.json").read_text())
TUNE_SEEDS = SEEDS["dev_seeds"][5:8]
HOLDOUT_SEEDS = SEEDS["dev_seeds"][10:13]
RB, RBA, RBAR = ["region", "bin"], ["bin", "region", "amount"], ["bin", "region", "amount", "rec"]
VARIANTS = {
    "L0_legacy_144": [RB, FULL],
    "L1_144_via36": [RB, RBA, FULL],
    "L2_144_via36_72": [RB, RBA, RBAR, FULL],
    "L3_flat_36": [RB, RBA],
    "L4_72_drop_card": [RB, RBAR],
    "L5_72_drop_rec": [RB, RBA + ["card"]],
    "L6_72_via36": [RB, RBA, RBAR],
}
CFG = SimConfig()


def one(args):
    name, k, seed = args
    world = World(CFG, seed)
    params = AdaptiveParams.load()
    params.levels, params.prior_strength = VARIANTS[name], k
    rng = np.random.default_rng(np.random.SeedSequence([seed, 77]))
    res = run(world, AdaptiveRouter(CFG, rng, params), FailoverRecovery(0, 2))
    ad = metrics.adaptation_speed(res, world)
    agree = float((res.psp == world.oracle_psp[: res.n]).mean())
    return {"variant": name, "prior_strength": k, "seed": seed, "net_value_per_txn": res.value.mean(),
            "auth_rate_final": res.final_ok.mean(), "agree_with_oracle": agree, "adapt_txns": ad["txns_to_adapt"]}


def main(which="tune"):
    seeds = TUNE_SEEDS if which == "tune" else HOLDOUT_SEEDS
    out = ROOT / "evals" / "results" / "phase3b_levels_dev"
    out.mkdir(parents=True, exist_ok=True)
    if which == "tune":
        tasks = [(v, k, s) for v in VARIANTS for k in (5.0, 20.0) for s in seeds]
    else:
        tasks = [(v, k, s) for v, k in (x.split("@") and (x.split("@")[0], float(x.split("@")[1]))
                                      for x in sys.argv[2:]) for s in seeds]
    with Pool(4) as pool:
        rows = pool.map(one, tasks)
    df = pd.DataFrame(rows)
    df.to_csv(out / f"{which}_runs.csv", index=False)
    agg = df.groupby(["variant", "prior_strength"]).agg(
        net_value=("net_value_per_txn", "mean"), sd=("net_value_per_txn", "std"), auth=("auth_rate_final", "mean"),
        agree=("agree_with_oracle", "mean"), adapt=("adapt_txns", "mean")).sort_values("net_value", ascending=False)
    agg.round(4).to_csv(out / f"{which}_summary.csv")
    print(agg.round(4).to_string())


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "tune")
