"""Run one (router, recovery policy) strategy over a World."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import ACTION_NAMES, CASCADE, STOP
from .types import Outcome, RecoveryPolicy, Router, RouterState
from .world import World


@dataclass
class SimResult:
    n: int
    psp: np.ndarray  # first-attempt PSP
    first_ok: np.ndarray
    final_ok: np.ndarray
    value: np.ndarray  # net value per transaction (all attempts)
    fees: np.ndarray
    retry_cost: np.ndarray
    cause: np.ndarray  # hidden true cause of the first decline, -1 if approved
    action: np.ndarray  # recovery action kind, -1 if no decline, STOP if declined and not retried
    retried: np.ndarray
    retry_ok: np.ndarray

    @property
    def action_names(self):
        return ACTION_NAMES


def run(world: World, router: Router, recovery: RecoveryPolicy, n: int | None = None) -> SimResult:
    n = world.n if n is None else min(n, world.n)
    state = RouterState(0, n)
    psp_a = [0] * n
    first_ok = [False] * n
    final_ok = [False] * n
    value = [0.0] * n
    fees = [0.0] * n
    rcost = [0.0] * n
    cause_a = [-1] * n
    action_a = [-1] * n
    retried = [False] * n
    retry_ok = [False] * n
    margin = world.lists()["margin"]

    for i in range(n):
        state.t = i
        txn = world.txn(i)
        psp = router.route(txn, state)
        psp_a[i] = psp
        fixed, pct = world.attempt_cost(i, psp)
        cause = world.first_attempt(i, psp)
        if cause < 0:
            first_ok[i] = final_ok[i] = True
            fees[i] = fixed + pct
            value[i] = margin[i] - fees[i]
            router.observe(txn, psp, Outcome(True, None))
            continue
        fees[i] = fixed
        value[i] = -fixed
        cause_a[i] = cause
        code = world.observed_code(i, cause)
        router.observe(txn, psp, Outcome(False, code))
        action = recovery.decide(txn, psp, code, state)
        action_a[i] = action.kind
        if action.kind == STOP:
            continue
        if action.kind == CASCADE and (action.target_psp is None or action.target_psp == psp):
            raise ValueError("cascade needs a different target PSP")
        ok, dv, fee, rc = world.execute(i, psp, cause, action)
        retried[i] = True
        retry_ok[i] = ok
        final_ok[i] = ok
        value[i] += dv
        fees[i] += fee
        rcost[i] = rc

    return SimResult(
        n=n, psp=np.asarray(psp_a, np.int8), first_ok=np.asarray(first_ok, bool),
        final_ok=np.asarray(final_ok, bool), value=np.asarray(value, np.float64),
        fees=np.asarray(fees, np.float64), retry_cost=np.asarray(rcost, np.float64),
        cause=np.asarray(cause_a, np.int8), action=np.asarray(action_a, np.int8),
        retried=np.asarray(retried, bool), retry_ok=np.asarray(retry_ok, bool),
    )
