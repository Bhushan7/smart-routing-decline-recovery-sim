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
ALL = ("static", "rule_based", "adaptive_v1", "adaptive", "oracle_routing", "oracle")
FINAL_STRATEGIES = ("static", "rule_based", "naive_retry", "static_rules", "adaptive", "adaptive_rules",
                    "adaptive_agent", "oracle_routing", "oracle")
AGENT_STRATEGIES = ("static", "static_rules", "adaptive", "adaptive_rules", "adaptive_agent_v1", "adaptive_agent",
                    "oracle_routing", "oracle")


def build_strategy(name: str, world: World):
    if name == "static":
        return StaticRouter(2), FailoverRecovery(0, 2)
    if name == "rule_based":
        return RuleBasedRouter(), FailoverRecovery(0, 2)
    if name == "oracle_routing":
        return OracleRouter(world), FailoverRecovery(0, 2)
    if name == "oracle":
        return OracleRouter(world), OracleRecovery(world)
    if name in ("adaptive", "adaptive_v1"):
        from ..routers.adaptive import LEGACY_LEVELS, AdaptiveParams, AdaptiveRouter

        params = AdaptiveParams.load()
        if name == "adaptive_v1":  # Phase 3 design: 144 cells backing off to 12
            params.levels = [list(x) for x in LEGACY_LEVELS]
        rng = np.random.default_rng(np.random.SeedSequence([world.seed, 77]))
        return AdaptiveRouter(world.cfg, rng, params), FailoverRecovery(0, 2)
    if name == "naive_retry":  # reference only: retries every decline immediately, hard ones included
        from ..routers.recovery import AlwaysRetryNow

        return StaticRouter(2), AlwaysRetryNow()
    if name == "static_rules":
        from ..agent.agent import AgentRecovery

        return StaticRouter(2), AgentRecovery(world.cfg, mode="rules")
    if name in ("adaptive_rules", "adaptive_agent", "adaptive_agent_v1"):
        from ..agent.agent import AgentRecovery
        from ..agent.llm import StubLLM
        from ..routers.adaptive import AdaptiveParams, AdaptiveRouter

        rng = np.random.default_rng(np.random.SeedSequence([world.seed, 77]))  # same stream as "adaptive"
        mode = "rules" if name == "adaptive_rules" else "agent"
        llm = StubLLM("v1" if name == "adaptive_agent_v1" else "v2")
        return AdaptiveRouter(world.cfg, rng, AdaptiveParams.load()), AgentRecovery(world.cfg, llm=llm, mode=mode)
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
    order = list(dict.fromkeys(ALL + AGENT_STRATEGIES))
    return agg.reindex([s for s in order if s in agg.index])


def _final_worker(args):
    """One seed: run every strategy, return raw rows for the final evaluation."""
    from ..analysis import agent_eval

    cfg, seed, strategies = args
    world, res = run_seed(cfg, seed, strategies)
    oracle, static = res["oracle"], res["static"]
    nb, k = cfg.days, cfg.n_txn // cfg.days
    reg_mask = world.region[: cfg.n_txn] == cfg.drift_region
    out = {"rows": [], "ts": [], "seg": [], "guard": [], "dq": None, "cost": None, "examples": None}
    for name, r in res.items():
        row = {"seed": seed, "strategy": name, **metrics.summarize(r)}
        row["final_regret_vs_oracle"] = float(metrics.regret_curve(r, oracle)[-1])
        ad = metrics.adaptation_speed(r, world)
        row["adapt_txns"], row["adapt_status"] = ad["txns_to_adapt"], ad["status"]
        flagged = metrics.segment_guardrail(world, r, static) if name != "static" else []
        row["segments_worse_than_static"] = len(flagged)
        out["rows"].append(row)
        out["guard"] += [{"seed": seed, "strategy": name, **g} for g in flagged]
        b = metrics.binned(r, nb)
        regret = metrics.regret_curve(r, oracle)
        to_b = r.psp == cfg.drift_psp
        for j in range(nb):
            sl = slice(j * k, (j + 1) * k)
            in_r = reg_mask[sl]
            out["ts"].append({
                "seed": seed, "strategy": name, "bin": j, "t_frac": (j + 0.5) / nb,
                "auth_rate": b["auth_rate"][j], "net_value": b["net_value"][j],
                "cum_regret": float(regret[(j + 1) * k - 1]),
                "drift_psp_share_in_region": float(to_b[sl][in_r].mean()) if in_r.any() else float("nan"),
            })
        seg = world.segment[: r.n]
        n_s = np.bincount(seg, minlength=144)
        ok_s = np.bincount(seg, weights=r.final_ok.astype(float), minlength=144)
        out["seg"] += [{"seed": seed, "strategy": name, "segment": int(s), "n": int(n_s[s]),
                        "auth_rate": float(ok_s[s] / n_s[s])} for s in range(144) if n_s[s] > 0]
    ag = res["adaptive_agent"]
    lab = agent_eval.labeled_set(world, ag)
    dq = agent_eval.decision_quality(lab)
    by = dq.pop("exact_match_by_true_class")
    out["dq"] = {"seed": seed, **dq, **{f"exact_match_{c}": v for c, v in by.items()}}
    cost = agent_eval.agent_cost(ag)
    cost.pop("fallback_detail")
    out["cost"] = {"seed": seed, **cost}
    ex = lab.sample(n=min(150, len(lab)), random_state=seed)
    ex.insert(0, "seed", seed)
    out["examples"] = ex
    return out


def run_final(cfg: SimConfig, seeds: list[int], outdir: str | Path, strategies=FINAL_STRATEGIES,
              seed_set: str = "eval_frozen", workers: int = 4) -> None:
    """Final multi-seed evaluation, seeds processed in parallel. Writes RAW per-seed outputs."""
    from multiprocessing import Pool

    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    with Pool(workers) as pool:
        parts = pool.map(_final_worker, [(cfg, s, strategies) for s in seeds])
    cat = lambda key: [r for p in parts for r in p[key]]  # noqa: E731
    pd.DataFrame(cat("rows")).to_csv(out / "per_seed.csv", index=False)
    pd.DataFrame(cat("ts")).to_csv(out / "timeseries.csv", index=False)
    pd.DataFrame(cat("seg")).to_csv(out / "segment_auth.csv", index=False)
    pd.DataFrame(cat("guard"), columns=["seed", "strategy", "segment", "n", "delta"]).to_csv(
        out / "segment_guardrail.csv", index=False)
    pd.DataFrame([p["dq"] for p in parts]).to_csv(out / "agent_decision_quality.csv", index=False)
    pd.DataFrame([p["cost"] for p in parts]).to_csv(out / "agent_cost.csv", index=False)
    pd.concat([p["examples"] for p in parts]).to_csv(out / "agent_decision_examples.csv", index=False)
    (out / "run_info.json").write_text(json.dumps(
        {"seed_set": seed_set, "seeds": seeds, "git_commit": git_commit(), "strategies": list(strategies),
         "config": cfg.to_dict(), "agent_llm": "deterministic stub (no API key); NOT Claude",
         "note": "All numbers are simulated."}, indent=1, default=str))
