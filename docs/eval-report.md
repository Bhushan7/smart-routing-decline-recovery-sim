# Eval report

All numbers are **simulated** (synthetic data, simplified decline model). Work in progress: Phases 4 to 5 add the agent and final tables.

## Phase 3: adaptive router (frozen eval seeds 2000-2011, 300k txns each, run once)

Results: `evals/results/phase3_eval_frozen/`. Parameters tuned on dev seeds only (see `PM_DECISIONS.md`).

| Router | Net value / txn (mean, min-max) | Final auth rate (mean) | Regret vs oracle (mean) |
|---|---|---|---|
| Static + failover | 7.138 (7.114-7.160) | 87.22% | 113,379 |
| Rule-based | 7.149 (7.124-7.178) | 87.73% | 110,201 |
| Adaptive | 7.158 (7.130-7.193) | 87.03% | 107,367 |
| Oracle routing only | 7.310 (7.281-7.330) | 87.51% | 61,961 |
| Oracle (routing + recovery) | 7.516 (7.486-7.541) | 90.12% | 0 |

Paired differences across the 12 seeds:

| Comparison | Net value / txn | Seeds better | Final auth rate |
|---|---|---|---|
| Adaptive minus static | +0.020 (-0.006 to +0.044) | 10 of 12 | -0.18 pts |
| Adaptive minus rule-based | +0.009 (-0.012 to +0.022) | 9 of 12 | -0.70 pts |
| Rule-based minus static | +0.011 (-0.005 to +0.033) | 9 of 12 | +0.52 pts |

Adaptation speed (region transactions after drift until PSP_B share falls below 50% of its pre-drift share):
adaptive median 8,872 (range 7,543 to 12,227), reached in 12 of 12 seeds. Rule-based and static: never (they do not adapt). Oracle routing: 2,000 (the measurement window floor).

### Honest reading
- The adaptive router **does** beat static and rule-based on net value, but by a small margin (+0.28% vs static), and it captures only about 10% (range -4% to +24%) of the routing gap that the oracle shows is available.
- It **lowers** the final auth rate (-0.18 pts vs static, -0.70 vs rule-based). It optimizes net value, so it moves traffic to cheaper PSPs at some cost in approvals. The "approvals vs cost" trade-off is visible here.
- Segment guardrail: a median of 50 of 144 segments have a final auth rate worse than static by more than 0.5 pts (min 40, max 57). For reference the oracle routing-only benchmark has 27, because it also trades approvals for cost. So this is partly the objective, but the adaptive router is clearly worse than the oracle on this guardrail and needs attention.
- It reacts to the drift: PSP_B's share of REGION_2 traffic falls from about 37% to about 10%. It is slow compared with the oracle, and after the drift it is below static on net value for a while.

### Diagnosis (dev seed 1005; not a tuned result)
- The router learns: agreement with the oracle's best PSP rises from 43% (first tenth of the run) to about 70%, versus 21% for static.
- Learning is sample-limited: the best and second-best PSP differ by only 0.2 per txn on average (under 0.05 for 44% of txns), and 576 arms share 300k transactions (30 segments have fewer than 500 txns).
- Tripling volume to 900k raises the share of the routing gap captured from 11% to 39%.
- Forcing learning at the coarse 12-cell level (no segment detail) is worse than static (-16%), so the segment detail does carry signal.
- Tuning does not fix it: 18 parameter settings differ by about 0.4% net value, within seed noise.

## Phase 3b: improving the adaptive router's learning structure (new seed set, run once)

**Why.** Phase 3 showed the router is sample-limited (576 arms, 300k transactions). Option B was to
reduce the learning problem. The simulator's 144 segments and the guardrail are unchanged; only
what the router learns on changed, via a configurable hierarchy of learning cells.

**Choosing the structure (dev seeds only).** 7 hierarchies x 2 prior strengths on dev seeds 1005-1007,
confirmed on dev hold-out 1010-1012 (`evals/results/phase3b_levels_dev/`):

| Hierarchy (finest cell) | Net value / txn, tuning seeds | Hold-out |
|---|---|---|
| 72 cells (drop card_type), via 12 -> 36 -> 72 (chosen) | 7.199 | 7.185 |
| 72 cells, 12 -> 72 | 7.186 | 7.185 |
| 144 cells via 12 -> 36 -> 72 -> 144 | 7.180 | 7.162 |
| 144 cells via 12 -> 144 (Phase 3, v1) | 7.160 | 7.145 |
| Flat 36 cells (drop card_type and recurring) | 7.119 | not run |
| 72 cells (drop recurring) | 7.096 | not run |

Dropping `recurring` hurts badly (below static) because the simulated PSP_D has a large recurring effect.
Dropping `card_type` helps because the simulated card effect is small. **This is specific to how I built
the simulated world** (see limitations). Static on these dev seeds is about 7.14.

**Fresh seed set.** The v2 design was motivated partly by seeing results on the first frozen set, so
reporting it there would leak. I added `eval_seeds_v2` (3000-3011), never used for anything before.
The Phase 3 results on `eval_seeds` stand as reported. Results: `evals/results/phase3b_eval_frozen_v2/`.
The v1 design is re-run on the same new seeds for a like-for-like comparison (it reproduces Phase 3: 11% of gap).

| Router (v2 seeds, mean) | Net value / txn | Final auth rate | Regret vs oracle |
|---|---|---|---|
| Static + failover | 7.139 | 87.18% | 114,169 |
| Rule-based | 7.158 | 87.75% | 108,361 |
| Adaptive v1 (144 cells) | 7.158 | 87.01% | 108,396 |
| **Adaptive v2 (72-cell hierarchy)** | **7.192** | 87.23% | 98,151 |
| Oracle routing only | 7.311 | 87.49% | 62,496 |
| Oracle (routing + recovery) | 7.519 | 90.11% | 0 |

Paired differences over 12 seeds:

| Comparison | Net value / txn | Seeds better | Final auth rate |
|---|---|---|---|
| v2 minus static | +0.053 (+0.043 to +0.062) | 12 of 12 | +0.05 pts (-0.12 to +0.22) |
| v2 minus rule-based | +0.034 (+0.016 to +0.053) | 12 of 12 | -0.52 pts |
| v2 minus v1 | +0.034 (+0.024 to +0.052) | 12 of 12 | +0.21 pts |

- Share of the oracle routing gap captured: **31%** (range 25% to 37%), up from 11% for v1.
- Adaptation speed: median 5,864 region transactions (range 3,523 to 8,240), versus 8,485 for v1.
- Net cost per approval: 1.541 (static 1.516, rule-based 1.623).
- Segment guardrail: median **42** of 144 segments have a final auth rate more than 0.5 pts below static
  (range 35 to 47; v1: 50; oracle routing only: 28). Improved but still a real issue.

### Honest reading
- The structure change worked: the gain over static grew from +0.28% to +0.75% and holds in every seed, and the overall auth rate is no longer below static.
- The router still captures under a third of what the oracle routing benchmark shows is available, and it is still behind rule-based on auth rate (-0.52 pts) because it chases net value.
- Many segments still end up below static on auth rate. This needs a decision about whether the objective should include an auth-rate floor (a product question, not tuned here).
- Not done: learning from retry outcomes. Retries only happen after a decline, so their outcomes are a biased sample of approval probability.
