# Simulator assumptions (DRAFT for Gate 1)

Status of every item below: **proposed** until approved. Nothing here is real-world data.
All values are synthetic and every result derived from them is "simulated". The decline taxonomy is a
**simplified model**, not card-network rules. All names are generic (`PSP_A..D`, `BIN_GROUP_1..4`).

The simulator holds a **hidden truth**. Routers and the agent see only observables (segment, response
code, own history, own observed outcomes). Only the oracle router and the evals see the hidden truth.

---

## 1. Segments and traffic (proposed)

| Dimension | Values | Observable? |
|---|---|---|
| `bin_group` | BIN_GROUP_1..4 | yes |
| `card_type` | debit, credit | yes |
| `region` | REGION_1..3 | yes |
| `amount_band` | low (~20), mid (~80), high (~300), simulated currency units | yes |
| `recurring` | true / false | yes |
| `hour_of_day` | 0..23 | yes, **context only, not part of the segment** |
| `customer_id` | pool of ~50k synthetic ids | yes, drives decline history |

- Segment = bin_group x card_type x region x amount_band x recurring = 4x2x3x3x2 = **144 segments**.
- Segment mix is deliberately **uneven** (product of skewed marginals, e.g. REGION_1 50%, REGION_2 30%,
  REGION_3 20%; recurring 25%; high-amount 10%). Smallest segments get roughly 0.1% of traffic.
- **Default volume: 100k transactions per run** (decided at Gate 1; config range 100k to 500k).
- Learnability check: 144 segments x 4 PSPs = 576 arms. At 100k, the mean arm sees only ~170 trials under
  uniform allocation, but the smallest segments see far fewer. Plan: hierarchical backoff (see 5) and
  a documented minimum-trials rule. If Phase 3 shows the smallest segments cannot be learned, I will
  **merge segments (e.g. drop the card_type split in rare cells), not cut volume**, per the kickoff.

## 2. PSP archetypes and hidden approval probabilities (proposed)

Hidden approval probability for a first attempt:

```
logit(p) = base[psp]
         + bin_effect[bin_group] + card_effect[card_type] + region_effect[region]
         + amount_effect[amount_band] + recurring_effect[recurring] + hour_effect[hour]
         + interaction[psp, feature]        # what makes PSPs differ per segment
         + drift_effect(psp, region, t)
```

Targets are overall first-attempt approval rates before drift; exact coefficients live in
`config/` and are set once, then frozen (not tuned to flatter any router).

| PSP | Archetype | Approx. overall approval | Strong in | Weak in |
|---|---|---|---|---|
| PSP_A | cheap, mediocre | ~82% | none | high amounts, BIN_GROUP_3 |
| PSP_B | premium, regional strength | ~88% (REGION_2 ~92%) | REGION_2, credit | cost |
| PSP_C | mid-tier all-rounder | ~86% | even everywhere | no standout |
| PSP_D | recurring specialist | ~87% recurring, ~80% one-time | recurring | one-time, REGION_3 |

Segment-level spread between best and worst PSP is typically 3 to 10 points, so routing matters but
no PSP dominates everywhere. The best PSP **net of cost** differs from the best by approval alone in some
segments (that is the point of the objective in 3).

**Fees (simulated currency units):**

| PSP | Fixed per attempt | Percentage of amount, charged on approval only |
|---|---|---|
| PSP_A | 0.20 | 1.5% |
| PSP_B | 0.30 | 2.4% |
| PSP_C | 0.25 | 1.9% |
| PSP_D | 0.22 | 1.8% |

Assumption to confirm: percentage fee only on approved transactions, fixed fee on every attempt.

**Technical errors** are a separate PSP-level process (timeout, network error, degraded) with a base rate
of ~1% per attempt per PSP, rising during an incident and with an hour-of-day pattern
(slightly higher at hours 2 to 4 for one PSP). It is part of the decline stream, not the approval logit.

## 3. Objective function (proposed)

```
value(txn) = approved * margin(amount_band) - psp_fee - retry_cost
```

| Parameter | Default | Reasoning |
|---|---|---|
| margin(low / mid / high) | 1.00 / 3.00 / 8.00 | Gross margin on an approved sale before PSP fees. About 5%, 3.75%, 2.7% of the band amount, so that fees are material relative to margin. |
| `psp_fee` | per table in 2 | fixed on every attempt, percentage on approvals |
| `retry_cost` | 0.05 per extra attempt | ops and network overhead per retry beyond fees |
| delayed-retry abandonment | non-recurring: 15% of customers do not return; recurring: 0% | A delayed retry on a live checkout loses some customers. |

Routers optimize **expected net value**, not raw auth rate. Both are always reported.
All of these are config values and are **frozen before any tuning**.

Open consequence to be aware of: with these margins a cheap PSP can beat a premium one on net value for
low-amount segments even at a lower approval rate. That is intended.

## 4. Drift events (proposed)

| Event | When | What |
|---|---|---|
| Degradation | 60% through the run | PSP_B loses ~15 approval points in REGION_2 (logit shift -1.2). |
| Partial recovery | 80% through the run | PSP_B recovers about half of the loss in REGION_2. |

Fixed timing for all seeds so adaptation speed is comparable. PSP_B is chosen because it is the
strongest PSP in REGION_2, so a router that has learned to favor it must unlearn that.
A technical-incident window (elevated tech errors on one PSP for ~2% of the run) is **proposed as a
secondary event** to test the agent's PSP-health signal. Open question Q4.

## 5. Routers and learning structure (proposed)

- Static primary with failover: primary PSP_C, secondary PSP_A, failover on technical errors only.
- Rule-based by segment: rules written from observed outcomes in the **first 10% of a dev-seed run** (never from hidden truth, never from eval seeds). Frozen after writing.
- Adaptive: Thompson sampling, Beta(1,1) priors per (segment, PSP). Hierarchical backoff
  segment -> (region, bin_group) -> global, with prior strength borrowed from the parent
  (pseudo-count cap, initially 20). Reward is **net value**, modeled as Beta approval posterior x known
  fee and margin (fees are known to the router; approval probabilities are not).
- Guardrails (config): per-PSP traffic cap (initial 60% of any rolling window), minimum exploration floor
  (initial 2% uniform exploration per segment).
- Non-stationarity: sliding-window or discounted updates (decay factor) to allow adapting after drift;
  the decay value is a tunable on **dev seeds only**.
- Oracle: knows hidden approval probabilities (including drift) and picks the PSP with highest expected
  net value. Used only for regret.

## 6. Decline model (proposed)

When an attempt is not approved, the hidden **true cause** is drawn. Overall decline rate is
~12 to 16% of first attempts. True-cause split of declines before context adjustment:

| Class | Share of declines | Causes (within class) |
|---|---|---|
| Hard | 20% | STOLEN_CARD, INVALID_CARD, CLOSED_ACCOUNT, FRAUD_SUSPECTED (equal-ish) |
| Soft | 70% | INSUFFICIENT_FUNDS (40%), ISSUER_UNAVAILABLE (20%), AMOUNT_LIMIT (15%), VELOCITY (15%), AUTH_REQUIRED (10%) |
| Technical | 10% | PSP_TIMEOUT, NETWORK_ERROR, PSP_DEGRADED (these come from the PSP-level process in 2, so this share rises during incidents) |

"Ambiguous" is not a true class. It is how a decline is **displayed**.

**Observable code.** The agent sees a generic internal response code, not the cause:
- By default a cause produces its own specific code (e.g. `HARD_STOLEN_CARD`).
- With some probability the decline is instead shown as `AMBIGUOUS_GENERIC_DECLINE` or
  `AMBIGUOUS_DO_NOT_HONOR`: hard 20%, soft 35%, technical 25%. That makes roughly 30% of all
  declines ambiguous, and those are the agent's territory.
- Hard causes shown with their specific code are 100% reliable (simplification: no mislabeled hard
  codes). **Open question Q5**, because it makes the "never retry hard" rule easy.

**Context shifts the likelihood of the true cause for ambiguous codes** (the signal the agent can use):
- recurring + prior declines in the last 30 days: more INSUFFICIENT_FUNDS
- high amount band: more AMOUNT_LIMIT
- recent decline count high on the same customer within 1 hour: more VELOCITY
- PSP currently degraded (health stat): more TECHNICAL
- BIN_GROUP with elevated fraud decline rate (hidden, observable only through stats): more hard

## 7. Retry-success model per action (proposed)

Hidden success probability of a recovery attempt given the true cause. Cascade success also depends on
the target PSP's segment approval probability `p_target`. `s` = scale factor.

| True cause | retry_same_now | retry_same_delayed | cascade_to_X | stop |
|---|---|---|---|---|
| Hard (all four) | 0 | 0 | 0 | 0 |
| INSUFFICIENT_FUNDS | 0.03 | 0.30 (delay ~24h) | 0.03 | 0 |
| ISSUER_UNAVAILABLE | 0.25 | 0.50 (delay ~10min) | 0.35 x s(p_target) | 0 |
| AMOUNT_LIMIT | 0.02 | 0.05 | 0.05 | 0 |
| VELOCITY | 0.05 | 0.40 (delay ~1h) | 0.10 | 0 |
| AUTH_REQUIRED | 0.02 | 0.03 | 0.05 | 0 |
| PSP_TIMEOUT | 0.40 | 0.55 | 0.90 x s(p_target) | 0 |
| NETWORK_ERROR | 0.50 | 0.60 | 0.90 x s(p_target) | 0 |
| PSP_DEGRADED | 0.15 | 0.40 | 0.90 x s(p_target) | 0 |

- `s(p_target) = p_target / mean(p over PSPs)`, clipped to [0.5, 1.2].
- Net value of an action = P(success) x (margin - target-PSP fees, adjusted for abandonment on delay)
  minus certain costs (fixed fee + retry cost). **Stop = 0.** The oracle best action is the argmax,
  including stop when every retry has negative expected value.
- Hard declines: success is exactly 0, so any retry is a **wasted retry** (cost incurred, no recovery).
- Maximum **one recovery action per declined transaction** in the base design (Open question Q3).

This table is a plausibility model, not a claim about real issuers.

## 8. Metrics specifics (proposed)

- **Adaptation speed:** transactions in the degraded region after the drift event until the rolling
  share (window 2,000 region transactions) of traffic to PSP_B falls below 50% of its pre-drift share.
  Reported as median and range across seeds, with "never reached" counted explicitly.
- **Regret vs oracle:** cumulative gap in net value to oracle on the **same transaction stream**.
- **Segment guardrail:** per-segment auth-rate delta vs static, flagged if worse than -0.5 points
  with at least 200 transactions in the segment.
- **Intervals:** mean with min/max and 95% bootstrap interval over seeds.

## 9. Seed policy (proposed)

- `numpy.random.Generator`, seeds passed explicitly everywhere. No global RNG.
- One root seed per run; `SeedSequence.spawn` into independent streams: traffic, approval draws,
  decline causes, retry draws, router, agent. A router's choices never alter the traffic stream.
- **Common random numbers:** per transaction, pre-draw uniforms per PSP so routers are compared on
  the same luck (paired comparison). This reduces variance a lot and makes "oracle beats baselines" a
  stricter test.
- `dev_seeds`: 1000 to 1019 (20 seeds, all tuning). `eval_seeds`: 2000 to 2011 (12 seeds), frozen in
  `evals/seeds.json` in Phase 2, never tuned on.
- Each run writes seed, git commit hash, and full config into its output folder.

## 10. Gate 1 decisions

1. Volume: **100k per run** for now. This makes segment learning sparse, see 1 and Q8.
2. Margins and fees: accepted as drafted.
3. **One** recovery attempt per declined transaction.
4. Technical-incident window: **included** as a secondary drift event.
5. Hard declines surface as ambiguous only; no mislabeled soft codes.
6. Customer pool (~50k, rolling decline history): accepted.
7. Rule-based baseline learned from the first 10% of a dev-seed run: accepted.

## 11. Still open

8. **Segment count at 100k.** 144 segments x 4 PSPs is thin at this volume (~170 trials per arm on average, far fewer in small segments). Options:
   (a) keep 144 segments and rely on hierarchical backoff (no change to scope, slower and noisier learning);
   (b) reduce to ~48 segments by dropping `card_type` and `recurring` from the segment key (they stay as hidden effects and observable context).
   Recommendation: (a) first, with a Phase 3 check; fall back to (b) if the smallest segments cannot be learned. Your call, since it changes results.
