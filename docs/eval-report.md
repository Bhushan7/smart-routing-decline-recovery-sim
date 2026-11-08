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

## Phase 4: decline recovery and the agent (DEV seeds 1002-1006, 300k txns each)

All numbers simulated. Dev seeds only: the frozen sets are reserved for the Phase 5 report.
**Important limit: no `ANTHROPIC_API_KEY` was available, so every "agent" number below is the deterministic
stub LLM, not Claude.** The stub reads the same four tools and applies fixed rules of thumb. It tests the
plumbing and gives a heuristic baseline. It says nothing reliable about how Claude would perform.
Reproduce Claude numbers yourself with `python evals/run_agent_claude.py` (see "Measuring real Claude").
Results: `evals/results/phase4_agent_dev/`.

### Design
- **Rules layer** (code only, deterministic): hard codes stop; technical codes cascade to the healthiest other PSP; specific soft codes map to a fixed action (funds and velocity: delayed retry; issuer unavailable: short delayed retry; amount limit and auth required: stop). Ambiguous codes are the only ones it cannot settle.
- **Ambiguous default** (rules-only baseline): delayed retry. Chosen on dev seeds 1000-1001 by comparing fixed defaults on mean value per ambiguous decline: stop 0.00, retry now +0.47, cascade +0.96, delayed **+1.82**, oracle +2.14. Always-stop would have been a strawman.
- **Agent**: called only for ambiguous codes, with cache (code, PSP, segment bucket, context bucket) and a call cap. Four read-only tools. Guardrails in code: hard codes are never retried; invalid output, errors, refusals and cap hits fall back to the rules default and are logged.

### Results (mean over 5 dev seeds)

| Strategy | Net value / txn | Final auth rate | Soft recovery | Regret vs oracle | Segments worse than static |
|---|---|---|---|---|---|
| Static + failover | 7.138 | 87.16% | 0% | 113,597 | 0 |
| Static + rules recovery | 7.349 | 89.71% | 24.8% | 50,336 | 0 |
| Adaptive v2 + failover | 7.188 | 87.13% | 0% | 98,620 | 44.8 |
| **Adaptive v2 + rules recovery** | **7.393** | 89.69% | 24.8% | 37,116 | 1.0 |
| Adaptive v2 + stub agent v1 | 7.362 | 89.58% | 23.6% | 46,174 | 1.6 |
| Adaptive v2 + stub agent v2 (final) | 7.390 | 89.66% | 24.4% | 37,888 | 1.0 |
| Oracle routing only | 7.309 | 87.49% | 0% | 62,133 | 27 |
| Oracle (routing + recovery) | 7.516 | 90.11% | 24.8% | 0 | 4 |

Paired differences (net value per txn, 5 seeds):

| Comparison | Mean | Seeds better | Auth |
|---|---|---|---|
| Rules recovery vs failover-only (adaptive) | **+0.205** | 5 of 5 | +2.56 pts |
| Static + rules recovery vs static | +0.211 | 5 of 5 | +2.55 pts |
| Adaptive + rules vs static + rules (routing's contribution) | +0.044 | 5 of 5 | -0.02 pts |
| **Agent v2 vs rules-only (the ablation)** | **-0.003** | **0 of 5** | -0.03 pts |
| Agent v1 vs rules-only | -0.030 | 0 of 5 | -0.11 pts |

### Findings
1. **Decline recovery is the big lever in this simulation, not routing.** Even simple rules lift net value by about 3% and the auth rate by about 2.5 points, roughly four times the gain from adaptive routing, and the segment guardrail problem disappears (45 segments worse than static falls to 1) because recovery lifts approvals everywhere.
2. **The agent adds no measurable value over rules here (stub).** Agent v2 is statistically level with the rules-only baseline (-0.003, worse in every seed). That is a finding, not a bug.
3. **The ceiling for any agent is small.** A sensible default already captures 84.5% of the oracle's value on ambiguous declines. The remaining gap is 0.337 per ambiguous decline, about 0.014 per transaction (0.2% of net value). A perfect agent could not add much in this world.
4. **Cost is low and bounded**: 1,343 agent calls per 300k-txn run = 32.9 per 1,000 declines; the agent is invoked for 10.6% of ambiguous declines (cache serves 89.4%); 0 fallbacks. Token counts are character-based estimates for the stub (about 450 in / 47 out per call, 3.3 tool calls), so the estimated 0.09 per 1,000 declines at Opus-class list prices is indicative only. Real latency is unmeasured (stub is instant).
5. Wasted retries on hard declines are unavoidable without a signal: about 1,650 per run are hard declines displayed as ambiguous (20% of hard declines), and every ambiguous-handling policy retries them. They cost fees and ops time only. Rules never retry a hard-coded decline (tested).
6. Retry efficiency falls from 0.87 (failover-only retries are mostly technical, which usually work) to 0.33 with recovery, because many more retries are speculative. Net value rises anyway.

### Agent decision quality vs oracle (63,480 ambiguous declines pooled)

| | Exact match | Mean value gap | Share of oracle value |
|---|---|---|---|
| Always stop | n/a | 2.174 | 0% |
| Rules default (delayed retry) | n/a | 0.337 | 84.5% |
| Stub agent v1 | 51.9% | 1.027 | 52.7% |
| Stub agent v2 (final) | 55.6% | 0.396 | 81.8% |

By true cause class (v2): soft 68.9% exact; technical 1.8% (the oracle wants a cascade but nothing observable flags the PSP); hard 0.3% (oracle says stop, but hard looks identical to soft here).

### Failure analysis: five real bad decisions (stub agent v2, dev seeds)
Full rows: `failure_cases_adaptive_agent.csv`; one per distinct (true cause, agent action) pair, costliest first.

| # | Case | What happened | Root cause | Fix |
|---|---|---|---|---|
| 1 | seed 1006, txn 171932: high amount, one-time, PSP_B, `AMBIGUOUS_DO_NOT_HONOR`, true cause PSP degraded | Agent delayed retry on the same PSP. Oracle: cascade to PSP_C. Gap 26.5 | A technical decline at the normal background rate carries no observable signal; PSP_B was not flagged | Burst detection on tech-coded and timeout rates per PSP, latency data |
| 2 | seed 1006, txn 24901: same profile, true cause PSP timeout. Gap 21.7 | Same | Same | Same |
| 3 | seed 1005, txn 30700: same profile, true cause network error, one recent decline. Gap 19.6 | Same, the weak "recent decline" hint pointed to velocity | Context signals are weak and overlap | Calibrated cause likelihoods from labeled history |
| 4 | seed 1003, txn 109939 (36.6% of the run): recurring, high amount, PSP_C, true cause insufficient funds | Cascaded to PSP_D because PSP_C was flagged degraded; oracle: delayed retry. Gap 10.6 | The flag was **correct**: this is inside PSP_C's real incident window (35% to 37%). The failure is the fixed rule order: "degraded PSP" overrides the stronger recurring-payment evidence, though even during an incident most declines are not technical | Weigh the evidence (e.g. incident rate vs recurring-funds likelihood) instead of a strict priority order |
| 5 | seed 1004, txn 720 (0.2% of the run): one-time, high amount, PSP_A, true cause velocity, one recent decline | Cascaded to PSP_B; oracle: delayed retry. Gap 10.1 | Cold start: almost no retry outcomes yet, so the estimates are the rounded priors, and with a margin of 45 a weakly positive cascade estimate wins. Estimates are also pooled across contexts, so they cannot see that this customer is velocity-prone | Context-conditional estimates, and a warm-up policy that defaults to the rules action until enough outcomes exist |

The first stub version (v1) failed worse: its "stop on large one-time amounts" rule threw away value because a recovery's payoff grows with the amount (v1 captured only 52.7% of oracle value; v2 removes the rule).
The fix to v2 was made after reading dev-seed failures, so v1 and v2 are both reported.

### Measuring real Claude
Needs an API key and spends money (rough planning figure, unmeasured: about 600 calls x 2 to 3k input tokens). Command, on a dev seed with a hard call cap:
```
export ANTHROPIC_API_KEY=...   # never commit it
python evals/run_agent_claude.py --n 60000 --max-calls 600
```
It prints net value, decision quality vs the oracle, real tokens, latency and fallbacks, and saves the labeled set. `--stub` runs the same code path with no API. The Claude client has unit tests with a fake client (tool loop, usage, refusal, fallbacks) but **has never been run against the live API**.
