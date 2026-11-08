import numpy as np
import pytest

from src.analysis import metrics
from src.routers.adaptive import AdaptiveParams, AdaptiveRouter
from src.routers.recovery import FailoverRecovery
from src.simulator.config import SimConfig
from src.simulator.engine import run
from src.simulator.types import RouterState
from src.simulator.world import World

CFG = SimConfig(n_txn=60_000)


def make(world, seed=5, **kw):
    params = AdaptiveParams(**{**AdaptiveParams().to_dict(), **kw})
    return AdaptiveRouter(world.cfg, np.random.default_rng(seed), params)


@pytest.fixture(scope="module")
def world():
    return World(CFG, 1000)


def test_deterministic_given_seed(world):
    a = run(world, make(world, 5), FailoverRecovery(0, 2), n=15_000)
    b = run(world, make(world, 5), FailoverRecovery(0, 2), n=15_000)
    c = run(world, make(world, 6), FailoverRecovery(0, 2), n=15_000)
    assert np.array_equal(a.psp, b.psp) and np.array_equal(a.value, b.value)
    assert not np.array_equal(a.psp, c.psp)


def test_traffic_cap_respected(world):
    cap, win = 0.40, 1000
    res = run(world, make(world, traffic_cap=cap, cap_window=win, explore_floor=0.0),
              FailoverRecovery(0, 2), n=30_000)
    for psp in range(4):
        x = (res.psp == psp).astype(float)
        roll = np.convolve(x, np.ones(win), "valid") / win
        assert roll.max() <= cap + 2.0 / win, (psp, roll.max())


def test_cap_binds_when_one_psp_dominates(world):
    # with a tight cap the router must spread traffic even though one PSP is best
    res = run(world, make(world, traffic_cap=0.30, explore_floor=0.0), FailoverRecovery(0, 2), n=20_000)
    assert (np.bincount(res.psp, minlength=4) / res.n).max() < 0.34


def test_exploration_floor_reaches_every_psp(world):
    r = make(world, explore_floor=0.10)
    res = run(world, r, FailoverRecovery(0, 2), n=20_000)
    assert (np.bincount(res.psp, minlength=4) > 0).all()
    assert 0.07 < r.n_explore / r.n_routed < 0.13


def test_hierarchical_backoff_prior_follows_parent():
    cfg = SimConfig()
    r = AdaptiveRouter(cfg, np.random.default_rng(1), AdaptiveParams(prior_strength=20))
    # teach the region/bin parent that PSP 1 approves ~90% and PSP 0 ~50%, via OTHER segments
    from src.simulator.types import Outcome, Transaction

    for i in range(400):
        seg = 10 + (i % 5)
        t = Transaction(i, 0, 0, 1, 0, 0, 0, 0, 0, seg)
        r.observe(t, 1, Outcome(i % 10 != 0, None))
        r.observe(t, 0, Outcome(i % 2 == 0, None))
    a, b = r.posterior_params(segment=99, region=1, bin_group=0)  # unseen segment, same parent
    mean = a / (a + b)
    assert mean[1] > 0.8 and 0.4 < mean[0] < 0.6
    assert (a + b)[1] == pytest.approx(20.0)  # strength capped at prior_strength


def test_shifts_traffic_away_after_drift():
    cfg = SimConfig(n_txn=120_000)
    world = World(cfg, 1001)
    res = run(world, make(world, 3), FailoverRecovery(0, 2))
    ad = metrics.adaptation_speed(res, world, window=1000)
    assert ad["status"] == "adapted", ad
    reg = world.region == cfg.drift_region
    t = world.t_frac
    pre = res.psp[reg & (t >= 0.4) & (t < 0.6)] == cfg.drift_psp
    mid = res.psp[reg & (t >= 0.65) & (t < 0.8)] == cfg.drift_psp
    assert mid.mean() < 0.7 * pre.mean()


def test_router_learns_toward_oracle_choice():
    # Whether adaptive beats static on net value is an eval question (see evals/results), not a unit
    # test: at small volume learning cost can exceed the gain. Here we test that it learns.
    cfg = SimConfig(n_txn=120_000)
    world = World(cfg, 1002)
    res = run(world, make(world, 3), FailoverRecovery(0, 2))
    agree = res.psp == world.oracle_psp
    third = cfg.n_txn // 3
    static_agree = (np.full(cfg.n_txn, 2) == world.oracle_psp).mean()
    assert agree[-third:].mean() > agree[:third].mean() + 0.05
    assert agree.mean() > static_agree + 0.2
    # value gap to the oracle PSP shrinks as it learns
    ev_gap = world.ev1.max(1) - world.ev1[np.arange(cfg.n_txn), res.psp]
    assert ev_gap[-third:].mean() < ev_gap[:third].mean()


def test_router_never_reads_hidden_truth():
    import inspect

    import src.routers.adaptive as mod

    src = inspect.getsource(mod)
    for banned in ("p_appr", "p_eff", "oracle", "cause", "world"):
        assert banned not in src.replace("Hidden truth is never read", ""), banned
    assert RouterState  # interface import sanity
