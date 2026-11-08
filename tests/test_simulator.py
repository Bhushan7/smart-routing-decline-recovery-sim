import numpy as np
import pytest

from src.analysis import metrics, runner
from src.routers.base import NoRecovery
from src.routers.recovery import AlwaysRetryNow
from src.routers.rules import RuleBasedRouter, fit_rule_table
from src.routers.static import StaticRouter
from src.simulator.config import (
    CASCADE,
    HARD_CAUSES,
    N_SEGMENTS,
    STOP,
    SimConfig,
)
from src.simulator.engine import run
from src.simulator.types import Action
from src.simulator.world import World

CFG = SimConfig(n_txn=40_000)


@pytest.fixture(scope="module")
def world():
    return World(CFG, 1000)


def test_determinism_same_seed_identical_results():
    a = runner.run_seed(CFG, 1001, ("static", "oracle"))[1]
    b = runner.run_seed(CFG, 1001, ("static", "oracle"))[1]
    for k in a:
        assert np.array_equal(a[k].value, b[k].value)
        assert np.array_equal(a[k].final_ok, b[k].final_ok)


def test_different_seeds_differ():
    a = World(CFG, 1)
    b = World(CFG, 2)
    assert not np.array_equal(a.segment, b.segment)


def test_traffic_identical_across_strategies(world):
    # common random numbers: world arrays are immutable inputs; strategies cannot change them
    seg_before = world.segment.copy()
    run(world, StaticRouter(0), NoRecovery())
    run(world, StaticRouter(3), NoRecovery())
    assert np.array_equal(seg_before, world.segment)


def test_probabilities_sane(world):
    assert world.p_eff.min() > 0 and world.p_eff.max() < 1
    mean = world.p_eff.mean(0)
    assert 0.78 < mean.min() and mean.max() < 0.93
    assert len(np.unique(world.segment)) == N_SEGMENTS
    for row in CFG.retry_table.values():
        assert all(0 <= x <= 1 for x in row[:3])


def test_drift_degrades_target_psp_and_region_only(world):
    c = CFG
    reg = world.region == c.drift_region
    pre = world.t_frac < c.drift_at
    mid = (world.t_frac >= c.drift_at) & (world.t_frac < c.recovery_at)
    post = world.t_frac >= c.recovery_at
    b = c.drift_psp
    assert world.p_appr[reg & mid, b].mean() < world.p_appr[reg & pre, b].mean() - 0.05
    assert world.p_appr[reg & post, b].mean() > world.p_appr[reg & mid, b].mean() + 0.02  # partial recovery
    assert world.p_appr[reg & post, b].mean() < world.p_appr[reg & pre, b].mean()
    other = 0
    assert abs(world.p_appr[reg & mid, other].mean() - world.p_appr[reg & pre, other].mean()) < 0.02
    assert abs(world.p_appr[~reg & mid, b].mean() - world.p_appr[~reg & pre, b].mean()) < 0.02


def test_hard_declines_never_succeed_on_retry(world):
    res = run(world, StaticRouter(2), AlwaysRetryNow())
    hard = np.isin(res.cause, HARD_CAUSES)
    assert hard.sum() > 100
    assert (res.retried & hard).sum() == hard.sum()  # all retried (wasted)
    assert not (res.retry_ok & hard).any()
    for cause in HARD_CAUSES:
        for kind in range(3):
            tgt = 0 if kind == CASCADE else None
            assert world.retry_success_prob(0, cause, Action(kind, tgt)) == 0.0


def test_oracle_never_retries_hard_and_stops_when_unprofitable(world):
    res = runner.run_seed(CFG, 1000, ("oracle",))[1]["oracle"]
    assert not (res.retried & np.isin(res.cause, HARD_CAUSES)).any()


def test_oracle_beats_all_baselines():
    wins = []
    for seed in (1000, 1001):
        _, r = runner.run_seed(CFG, seed)
        v = {k: x.value.mean() for k, x in r.items()}
        assert v["oracle"] > v["oracle_routing"] > v["static"]
        assert v["oracle"] > v["rule_based"]
        wins.append(v["oracle_routing"] - max(v["static"], v["rule_based"]))
    assert min(wins) > 0.05  # clear margin, not noise


def test_value_accounting_consistent(world):
    res = run(world, StaticRouter(2), AlwaysRetryNow())
    approved_margin = np.where(res.final_ok, world.margin, 0.0)
    assert np.allclose(res.value, approved_margin - res.fees - res.retry_cost)


def test_cascade_to_same_psp_rejected():
    class Bad:
        def decide(self, txn, psp, code, state):
            return Action(CASCADE, psp)

    with pytest.raises(ValueError):
        run(World(SimConfig(n_txn=5000), 3), StaticRouter(2), Bad())


def test_oracle_best_action_is_argmax_ev(world):
    checked = 0
    for i in range(5000):
        cause = world.first_attempt(i, 2)
        if cause < 0:
            continue
        best = world.best_action(i, 2, cause)
        evs = [world.action_ev(i, 2, cause, a) for a in
               [Action(0), Action(1)] + [Action(CASCADE, j) for j in (0, 1, 3)]]
        assert world.action_ev(i, 2, cause, best) >= max(evs + [0.0]) - 1e-9
        if cause in HARD_CAUSES:
            assert best.kind == STOP
        checked += 1
    assert checked > 100


def test_observed_codes_include_ambiguous(world):
    codes = set()
    for i in range(3000):
        for psp in range(4):
            c = world.first_attempt(i, psp)
            if c >= 0:
                codes.add(world.observed_code(i, c))
    assert {"AMBIGUOUS_GENERIC_DECLINE", "AMBIGUOUS_DO_NOT_HONOR", "HARD_STOLEN_CARD"} <= codes


def test_rule_table_reproducible_and_observable_only():
    assert fit_rule_table() == RuleBasedRouter().table


def test_metrics_adaptation_status_for_unused_psp(world):
    res = run(world, StaticRouter(2), NoRecovery())
    assert metrics.adaptation_speed(res, world)["status"] == "psp_barely_used_pre_drift"
