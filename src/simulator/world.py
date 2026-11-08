"""Seeded world: traffic stream, hidden approval truth, drift, decline causes, retry truth.

All randomness is pre-drawn per transaction (common random numbers), so every router sees the
same traffic and the same luck. A router's choices never alter the random streams.
"""
from __future__ import annotations

import numpy as np

from .config import (
    AMBIGUOUS_CODES,
    CASCADE,
    CAUSES,
    HARD_CAUSES,
    N_PSP,
    RETRY_DELAYED,
    RETRY_NOW,
    SOFT_CAUSES,
    STOP,
    SimConfig,
    cause_class,
)
from .types import Action, Transaction


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


class World:
    def __init__(self, cfg: SimConfig, seed: int):
        self.cfg = cfg
        self.seed = seed
        n = cfg.n_txn
        self.n = n
        ss = np.random.SeedSequence(seed)
        r_traffic, r_appr, r_decl, r_retry, r_cust = (np.random.default_rng(s) for s in ss.spawn(5))

        # ---- traffic ----
        self.bin = r_traffic.choice(4, size=n, p=cfg.p_bin)
        self.card = r_traffic.choice(2, size=n, p=cfg.p_card)
        self.region = r_traffic.choice(3, size=n, p=cfg.p_region)
        self.amount = r_traffic.choice(3, size=n, p=cfg.p_amount)
        self.rec = (r_traffic.random(n) < cfg.p_recurring).astype(np.int64)
        self.hour = (np.arange(n) * cfg.days * 24 // n) % 24
        self.segment = (((self.bin * 2 + self.card) * 3 + self.region) * 3 + self.amount) * 2 + self.rec
        self.customer = r_cust.integers(0, cfg.customer_pool, n)
        propensity = r_cust.gamma(1.0, 1.0, cfg.customer_pool)
        self.recent = np.minimum(3, r_cust.poisson(0.4 * propensity[self.customer]))
        self.amt = np.asarray(cfg.amount_value)[self.amount]
        self.margin = np.asarray(cfg.margin)[self.amount]
        self.t_frac = np.arange(n) / n

        # ---- hidden approval truth [n, P] ----
        self.p_appr = _sigmoid(self._logit())
        self.tech_rate = self._tech_rate()
        self.p_eff = self.p_appr * (1.0 - self.tech_rate)  # P(approved on first attempt)
        self.u_app = r_appr.random((n, N_PSP))
        self.u_tech = r_appr.random((n, N_PSP))

        # ---- decline causes (drawn once per txn; selected by how the attempt fails) ----
        self.cause_nontech = self._nontech_cause(r_decl.random(n), r_decl.random(n))
        self.cause_tech = self._tech_cause(r_decl.random((n, N_PSP)))
        self.u_disp = r_decl.random((n, 2))
        self.u_retry = r_retry.random(n)

        # first-attempt expected net value per PSP (fee-aware), used by the oracle router
        fixed = np.asarray(cfg.fixed_fee)
        pct = np.asarray(cfg.pct_fee)
        self.ev1 = self.p_eff * (self.margin[:, None] - pct[None, :] * self.amt[:, None]) - fixed[None, :]
        self.oracle_psp = self.ev1.argmax(axis=1)
        self._lists = None

    # ------------------------------------------------------------------ truth
    def _logit(self):
        c = self.cfg
        shared = (
            np.asarray(c.bin_effect)[self.bin]
            + np.asarray(c.card_effect)[self.card]
            + np.asarray(c.region_effect)[self.region]
            + np.asarray(c.amount_effect)[self.amount]
            + c.recurring_effect * self.rec
            + c.night_effect * (self.hour <= 5)
        )
        lg = np.empty((self.n, N_PSP))
        for j in range(N_PSP):
            lg[:, j] = c.base_logit[j] + shared
        # PSP-specific interactions: what makes PSPs differ per segment
        lg[:, 0] += -0.4 * (self.amount == 2) - 0.4 * (self.bin == 2)  # PSP_A: weak on big tickets
        lg[:, 1] += 0.45 * (self.region == 1) + 0.2 * (self.card == 1)  # PSP_B: regional strength
        lg[:, 3] += 0.6 * self.rec - 0.4 * (1 - self.rec) - 0.4 * (self.region == 2)  # PSP_D
        # drift and partial recovery
        in_region = self.region == c.drift_region
        lg[:, c.drift_psp] += np.where(
            in_region & (self.t_frac >= c.drift_at),
            np.where(self.t_frac >= c.recovery_at, c.recovery_logit, c.drift_logit),
            0.0,
        )
        return lg

    def _tech_rate(self):
        c = self.cfg
        tr = np.full((self.n, N_PSP), c.tech_base)
        tr[:, c.tech_night_psp] += c.tech_night_extra * ((self.hour >= 2) & (self.hour <= 4))
        inc = (self.t_frac >= c.incident_start) & (self.t_frac < c.incident_end)
        tr[inc, c.incident_psp] = c.incident_rate
        return tr

    def _nontech_cause(self, u_hs, u_c):
        c = self.cfg
        n = self.n
        w_hard = np.ones((n, 4))
        w_hard[:, 3] *= np.where(self.bin == 2, 2.0, 1.0)  # one BIN group is fraud-heavy
        w_soft = np.tile(np.asarray(c.soft_weights), (n, 1))
        w_soft[:, 0] *= np.where(self.rec == 1, 1.3, 1.0) * (1 + 0.15 * self.recent)
        w_soft[:, 2] *= np.where(self.amount == 2, 2.0, 1.0)
        w_soft[:, 3] *= np.where(self.recent >= 2, 2.5, 1.0)
        is_hard = u_hs < c.hard_share_nontech
        out = np.empty(n, dtype=np.int64)
        for mask, w, offset in ((is_hard, w_hard, 0), (~is_hard, w_soft, 4)):
            cum = np.cumsum(w[mask] / w[mask].sum(axis=1, keepdims=True), axis=1)
            out[mask] = offset + (u_c[mask, None] > cum).sum(axis=1).clip(max=w.shape[1] - 1)
        return out

    def _tech_cause(self, u):
        c = self.cfg
        p_deg = np.where(self.tech_rate > 0.05, c.degraded_prob_incident, c.degraded_prob_normal)
        return np.where(u < p_deg, 11, np.where(u < p_deg + (1 - p_deg) / 2, 9, 10))

    def lists(self):
        """Python-list views of hot arrays (much faster for the per-transaction loop)."""
        if self._lists is None:
            self._lists = {
                "bin": self.bin.tolist(), "card": self.card.tolist(), "region": self.region.tolist(),
                "amount": self.amount.tolist(), "rec": self.rec.tolist(), "hour": self.hour.tolist(),
                "customer": self.customer.tolist(), "recent": self.recent.tolist(),
                "segment": self.segment.tolist(), "u_app": self.u_app.tolist(),
                "u_tech": self.u_tech.tolist(), "p_appr": self.p_appr.tolist(),
                "tech_rate": self.tech_rate.tolist(), "cause_nt": self.cause_nontech.tolist(),
                "cause_t": self.cause_tech.tolist(), "u_disp": self.u_disp.tolist(),
                "u_retry": self.u_retry.tolist(), "amt": self.amt.tolist(),
                "margin": self.margin.tolist(),
            }
        return self._lists

    def txn(self, i: int) -> Transaction:
        L = self.lists()
        return Transaction(i, L["bin"][i], L["card"][i], L["region"][i], L["amount"][i],
                           L["rec"][i], L["hour"][i], L["customer"][i], L["recent"][i],
                           L["segment"][i])

    # ------------------------------------------------------------ first attempt
    def first_attempt(self, i: int, psp: int) -> int:
        """Return -1 if approved, else the hidden true cause index."""
        L = self.lists()
        if L["u_tech"][i][psp] < L["tech_rate"][i][psp]:
            return int(L["cause_t"][i][psp])
        if L["u_app"][i][psp] < L["p_appr"][i][psp]:
            return -1
        return int(L["cause_nt"][i])

    def observed_code(self, i: int, cause: int) -> str:
        """Response code the router/agent sees. Some declines of every class look ambiguous."""
        cls = cause_class(cause)
        k = {"hard": 0, "soft": 1, "tech": 2}[cls]
        u0, u1 = self.lists()["u_disp"][i]
        if u0 < self.cfg.ambiguous_prob[k]:
            return AMBIGUOUS_CODES[0 if u1 < 0.5 else 1]
        return CAUSES[cause]

    # ------------------------------------------------------------ economics
    def attempt_cost(self, i: int, psp: int) -> tuple[float, float]:
        """(fixed fee paid on every attempt, percentage fee paid on approval only)."""
        return self.cfg.fixed_fee[psp], self.cfg.pct_fee[psp] * self.lists()["amt"][i]

    def retry_success_prob(self, i: int, cause: int, action: Action) -> float:
        c = self.cfg
        same_now, same_del, casc, _ = c.retry_table[cause]
        if action.kind == RETRY_NOW:
            return same_now
        if action.kind == RETRY_DELAYED:
            ab = 1.0 if self.lists()["rec"][i] else 1.0 - c.delay_abandon
            return same_del * ab
        if action.kind == CASCADE:
            if cause in c.cascade_scaled:
                row = self.p_eff[i]
                s = min(1.2, max(0.5, row[action.target_psp] / row.mean()))
                return min(1.0, casc * s)
            return casc
        return 0.0

    def action_ev(self, i: int, psp: int, cause: int, action: Action) -> float:
        """Expected net value of an action, from hidden truth. Stop = 0."""
        if action.kind == STOP:
            return 0.0
        tgt = action.target_psp if action.kind == CASCADE else psp
        fixed, pct = self.attempt_cost(i, tgt)
        m = self.lists()["margin"][i]
        p = self.retry_success_prob(i, cause, action)
        return p * (m - pct) - fixed - self.cfg.retry_cost

    def best_action(self, i: int, psp: int, cause: int) -> Action:
        """Oracle best recovery action: highest expected net value (ties prefer stop)."""
        best, best_v = Action(STOP), 0.0
        cands = [Action(RETRY_NOW), Action(RETRY_DELAYED, None, self.cfg.retry_table[cause][3])]
        cands += [Action(CASCADE, j) for j in range(N_PSP) if j != psp]
        for a in cands:
            v = self.action_ev(i, psp, cause, a)
            if v > best_v + 1e-12:
                best, best_v = a, v
        return best

    def execute(self, i: int, psp: int, cause: int, action: Action):
        """Run a recovery action. Returns (success, value_delta, fee_paid, retry_cost_paid)."""
        if action.kind == STOP:
            return False, 0.0, 0.0, 0.0
        tgt = action.target_psp if action.kind == CASCADE else psp
        fixed, pct = self.attempt_cost(i, tgt)
        p = self.retry_success_prob(i, cause, action)
        ok = self.lists()["u_retry"][i] < p
        rc = self.cfg.retry_cost
        fee = fixed + (pct if ok else 0.0)
        val = (self.lists()["margin"][i] if ok else 0.0) - fee - rc
        return ok, val, fee, rc

    def is_hard(self, cause: int) -> bool:
        return cause in HARD_CAUSES

    def is_soft(self, cause: int) -> bool:
        return cause in SOFT_CAUSES
