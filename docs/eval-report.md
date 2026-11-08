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
