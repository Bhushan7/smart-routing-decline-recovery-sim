"""Multi-seed runner. Writes seed, git commit and config next to every output."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

from ..routers.base import NoRecovery
from ..routers.oracle import OracleRouter
from ..routers.recovery import FailoverRecovery, OracleRecovery
from ..routers.rules import RuleBasedRouter
from ..routers.static import StaticRouter
from ..simulator.config import SimConfig
from ..simulator.engine import run
from ..simulator.world import World
from . import metrics

BASELINES = ("static", "rule_based", "oracle_routing", "oracle")
ALL = ("static", "rule_based", "adaptive", "oracle_routing", "oracle")


def build_strategy(name: str, world: World):
    if name == "static":
        return StaticRouter(2), FailoverRecovery(0, 2)
    if name == "rule_based":
        return RuleBasedRouter(), FailoverRecovery(0, 2)
    if name == "oracle_routing":
        return OracleRouter(world), FailoverRecovery(0, 2)
    if name == "oracle":
        return OracleRouter(world), OracleRecovery(world)
    if name == "adaptive":
        from ..routers.adaptive import AdaptiveRouter

        rng = np.random.default_rng(np.random.SeedSequence([world.seed, 77]))
        return AdaptiveRouter(world.cfg, rng), FailoverRecovery(0, 2)
    if name == "no_recovery":
        return StaticRouter(2), NoRecovery()
    raise KeyError(name)


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def run_seed(cfg: SimConfig, seed: int, strategies=BASELINES, builder=build_strategy):
    world = World(cfg, seed)
    results = {s: run(world, *builder(s, world)) for s in strategies}
    return world, results


def run_many(cfg: SimConfig, seeds: list[int], outdir: str | Path, strategies=BASELINES,
             builder=build_strategy, seed_set: str = "dev") -> pd.DataFrame:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    rows, ts_rows, guard_rows = [], [], []
    for seed in seeds:
        world, results = run_seed(cfg, seed, strategies, builder)
        oracle = results["oracle"]
        for name, res in results.items():
            row = {"seed": seed, "strategy": name, **metrics.summarize(res)}
            row["final_regret_vs_oracle"] = float(metrics.regret_curve(res, oracle)[-1])
            ad = metrics.adaptation_speed(res, world)
            row["adapt_txns"] = ad["txns_to_adapt"]
            row["adapt_status"] = ad["status"]
            row["segments_worse_than_static"] = (
                len(metrics.segment_guardrail(world, res, results["static"])) if "static" in results else None
            )
            rows.append(row)
            if name not in ("static", "oracle", "oracle_routing") and "static" in results:
                for g in metrics.segment_guardrail(world, res, results["static"]):
                    guard_rows.append({"seed": seed, "strategy": name, **g})
            nb = cfg.days
            b = metrics.binned(res, nb)
            regret = metrics.regret_curve(res, oracle)
            k = res.n // nb
            reg = world.region[: res.n] == cfg.drift_region
            to_b = (res.psp == cfg.drift_psp)
            for j in range(nb):
                sl = slice(j * k, (j + 1) * k)
                in_r = reg[sl]
                share_b = float(to_b[sl][in_r].mean()) if in_r.any() else float("nan")
                ts_rows.append({
                    "seed": seed, "strategy": name, "bin": j, "t_frac": (j + 0.5) / nb,
                    "auth_rate": b["auth_rate"][j], "net_value": b["net_value"][j],
                    "cum_regret": float(regret[(j + 1) * k - 1]), "drift_psp_share_in_region": share_b,
                })
    df = pd.DataFrame(rows)
    df.to_csv(out / "per_seed.csv", index=False)
    pd.DataFrame(ts_rows).to_csv(out / "timeseries.csv", index=False)
    pd.DataFrame(guard_rows, columns=["seed", "strategy", "segment", "n", "delta"]).to_csv(
        out / "segment_guardrail.csv", index=False)
    (out / "run_info.json").write_text(json.dumps(
        {"seed_set": seed_set, "seeds": seeds, "git_commit": git_commit(),
         "strategies": list(strategies), "config": cfg.to_dict(),
         "note": "All numbers are simulated."}, indent=1, default=str))
    return df


def aggregate(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["auth_rate_first", "auth_rate_final", "net_value_per_txn", "net_cost_per_approval",
            "retry_efficiency", "wasted_retries_hard", "soft_recovery_rate", "final_regret_vs_oracle"]
    g = df.groupby("strategy")[cols]
    agg = g.mean().add_suffix("_mean").join(g.min().add_suffix("_min")).join(g.max().add_suffix("_max"))
    return agg.reindex([s for s in ALL if s in agg.index])
