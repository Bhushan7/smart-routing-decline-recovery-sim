# Eval report

All numbers in this repository are **simulated**: synthetic traffic, invented PSPs, a simplified decline model.
Nothing here describes real-world performance. The "agent" results use a **deterministic stub LLM, not Claude**.

Contents: [Methodology](#methodology) | [Final results (Phase 5)](#final-results-phase-5) | [Limitations](#limitations) |
history: [Phase 3](#phase-3-adaptive-router-frozen-eval-seeds-2000-2011-300k-txns-each-run-once) ·
[Phase 3b](#phase-3b-improving-the-adaptive-routers-learning-structure-new-seed-set-run-once) ·
[Phase 4](#phase-4-decline-recovery-and-the-agent-dev-seeds-1002-1006-300k-txns-each)

## Methodology

- **Simulator**: 300k transactions per run, 144 segments, 4 PSPs with hidden per-segment approval probabilities, a drift event
  (PSP_B degrades in REGION_2 at 60% of the run, partly recovers at 80%), a PSP_C incident window (35% to 37%), and hidden
  decline causes. Details and every assumption: `docs/simulator-assumptions.md`.
- **Common random numbers**: every strategy sees the same traffic and the same pre-drawn luck, so comparisons are paired.
- **Objective**: net value per transaction = margin on approvals - PSP fees - retry costs. Auth rate is always reported next to it.
- **Strategies**: Static + failover (PSP_C primary, PSP_A on technical errors); Rule-based (18 coarse cells, fitted from observable
  early dev-seed traffic); Naive retry-everything (reference only); Static + rules recovery; Adaptive router (Thompson sampling,
  failover-only recovery); Adaptive + rules-only recovery (the ablation); Adaptive + agent (router 4, stub LLM);
  Oracle routing only; Oracle (routing + recovery). Oracles use hidden truth and exist only as benchmarks.
- **Statistics**: mean across seeds, min to max, and a 95% percentile bootstrap interval of the mean (10,000 resamples).
  Paired differences are computed seed by seed. Intervals reflect seed-to-seed variance only. They cannot capture the risk
  that the simulator itself is wrong, so they are narrow by construction and should not be over-read.
- **Seed policy and honest disclosure** (`evals/seeds.json`):

| Seed set | Used for |
|---|---|
| dev 1000-1019 | everything during development: the rule-based table (1000), router tuning (1005-1007, hold-out 1010-1012), the rules default for ambiguous codes (1000-1001), the Phase 4 agent evaluation and stub revision (1002-1006) |
| eval 2000-2011 | Phase 3 results for the first router design only. The second design was motivated partly by seeing them, so they are **not** used for final results |
| eval v2 3000-3011 | Phase 3b router comparison, then this final evaluation. Nothing was changed after seeing the Phase 3b numbers: the router, its parameters and the rules and stub agent defaults were all fixed on dev seeds before this run |

The final run executed once (the script refuses to overwrite its output folder).

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

## Final results (Phase 5)

Seeds 3000-3011 (12), 300k transactions each. Raw per-seed outputs, charts and the dashboard source data are in
`evals/results/phase5_final_eval/`. View with `make demo`.

### Headline (simulated, stub LLM agent)

> Adaptive routing plus decline recovery improved simulated auth rate by **2.54 points** (95% CI 2.49 to 2.59) over static
> routing and recovered **24.2%** of soft declines (static: 0%). Compared with a naive retry-everything policy it cut failed
> retries by **48%** and retries on hard declines by **80%**.

Read this together with four qualifications, all backed by the tables below:
1. **Almost all of the gain comes from deterministic decline-recovery rules, not from routing and not from the agent.** Rules-only recovery alone adds +2.52 auth points over the adaptive router with failover-only recovery.
2. **The agent adds nothing measurable over rules** in this simulation: -0.003 net value per transaction, worse in 12 of 12 seeds (stub LLM; Claude is untested).
3. **Retries on hard declines increase against static** (0 to about 1,643 per run), because hard declines that show up under an ambiguous code cannot be told apart from soft ones. They cost fees and ops time only. The "cut" figures are against a naive policy that retries everything, a reference, not a recommendation.
4. Adaptive routing alone is a small gain (+0.75% net value, auth rate unchanged) and leaves 41.5 of 144 segments worse than static on auth rate; adding recovery brings that to about 2.4.

### Results by strategy (mean over 12 seeds; brackets: min to max)

| Strategy | Final auth rate | Net value / txn | Soft recovery | Recoveries per retry | Regret vs oracle |
|---|---|---|---|---|---|
| Static + failover | 87.18% [87.10, 87.25] | 7.138 [7.104, 7.154] | 0% | 0.874 | 114,169 |
| Rule-based | 87.75% [87.67, 87.84] | 7.158 [7.124, 7.183] | 0% | 0.877 | 108,361 |
| Naive: retry everything | 87.51% [87.40, 87.60] | 7.135 [7.104, 7.155] | 7.2% | 0.086 | 115,160 |
| Static + rules recovery | 89.74% [89.66, 89.82] | 7.351 [7.320, 7.369] | 25.0% | 0.344 | 50,560 |
| Adaptive (failover only) | 87.23% [87.05, 87.40] | 7.192 [7.151, 7.211] | 0% | 0.875 | 98,151 |
| Adaptive + rules recovery | 89.75% [89.61, 89.92] | 7.393 [7.351, 7.415] | 24.7% | 0.334 | 37,726 |
| **Adaptive + agent (stub)** | **89.72% [89.55, 89.88]** | **7.390 [7.347, 7.413]** | **24.2%** | 0.330 | 38,687 |
| Oracle routing only | 87.49% [87.40, 87.59] | 7.311 [7.270, 7.332] | 0% | 0.874 | 62,496 |
| Oracle (routing + recovery) | 90.12% [90.02, 90.17] | 7.519 [7.478, 7.545] | 24.9% | 0.362 | 0 |

Recoveries per retry (retry efficiency) is higher is better; it falls with recovery because many more retries are speculative.

### Paired differences (12 seeds)

| Comparison | Net value / txn (95% CI) | Auth rate, points (95% CI) | Seeds better |
|---|---|---|---|
| Adaptive + agent vs static | +0.252 (0.247 to 0.256) | +2.54 (2.49 to 2.59) | 12 of 12 |
| Adaptive + agent vs rule-based | +0.232 (0.225 to 0.239) | +1.96 (1.92 to 2.01) | 12 of 12 |
| Adaptive (failover only) vs static | +0.053 (0.050 to 0.057) | +0.05 (-0.01 to 0.11) | 12 of 12 on value; 8 of 12 on auth |
| Rules recovery vs failover-only (adaptive) | +0.201 (0.199 to 0.204) | +2.52 (2.50 to 2.55) | 12 of 12 |
| Static + rules recovery vs static | +0.212 (0.210 to 0.214) | +2.56 (2.54 to 2.58) | 12 of 12 |
| Routing on top of recovery (adaptive + rules vs static + rules) | +0.043 (0.038 to 0.048) | +0.02 (-0.04 to 0.07) | 12 of 12 on value |
| **Agent vs rules-only (ablation)** | **-0.003 (-0.004 to -0.003)** | -0.04 (-0.04 to -0.03) | **0 of 12** |

Attribution of the net-value gain of Adaptive + agent over static (+0.252): about +0.212 from rules recovery, +0.043 from adaptive routing,
-0.003 from the stub agent.

### Other metrics
- **Share of oracle value**: Adaptive + agent captures 98.3% of the oracle's net value, static 94.9% (stub; mean of paired ratios).
- **Regret vs oracle**: adaptive + agent has 66% lower cumulative regret than static (95% CI 65.0% to 67.2%).
- **Net cost per approval** rises with recovery (1.565 vs 1.516 for static): recovered sales cost extra fees and retry costs, but each is worth more than it costs.
- **Adaptation speed**: adaptive routers shift away from the degraded PSP_B in a median of **5,864** REGION_2 transactions after the drift (reached in 12 of 12 seeds); the oracle needs 2,000, the measurement floor. Rule-based and static never shift. The router is not tuned further for speed.
- **Segment guardrail** (final auth rate worse than static by more than 0.5 points, segments with at least 200 transactions; mean count per seed, of 144): static 0, **adaptive failover-only 41.5**, rule-based 16.0 (worst segment up to -28 points: REGION_2, high amount, recurring, BIN_GROUP_3, where the coarse 18-cell rules, which ignore BIN group, send traffic to PSP_A, weak on large tickets and on that BIN group), oracle routing only 28.0, **adaptive + agent 2.4**, adaptive + rules 2.3. Averaging each segment across seeds first gives 33 worse segments for adaptive failover-only and 0 for adaptive + agent (`segment_guardrail.png`). Routing without recovery trades approvals for cost in about a quarter of segments; recovery removes that.

### Agent: decision quality and cost (stub LLM, 12 seeds, about 12,500 ambiguous declines per run)
| | Value |
|---|---|
| Exact match with oracle best action | 54.2% (soft causes 67.2%, technical 2.2%, hard 0.01%) |
| Share of oracle value captured on ambiguous declines | 81.3% (rules default, delayed retry: 84.5%; always stop: 0%) |
| Agent calls per 1,000 declines | 33.0 (10.6% of ambiguous declines; 89.4% served from cache) |
| Fallbacks to rules | 0 |
| Tool calls per agent call | 3.3 |
| Tokens per call (estimated from characters) | about 453 in, 47 out |
| Estimated cost per 1,000 declines at Opus-class list price | about 0.09 (indicative only) |
| Latency | not measured (stub) |

The ceiling is small: the rules default already captures 84.5% of the oracle value on ambiguous declines, which is worth about 0.2% of net value to any agent.

### Failure analysis
Five real bad agent decisions with root causes and fixes are in the Phase 4 section below (dev seeds, final stub). The pattern: technical declines
that look like any other ambiguous decline (no observable signal outside incidents), a fixed rule order that lets "degraded PSP" override stronger
evidence, and pooled retry estimates that ignore context. The labeled examples for the final run are in `agent_decision_examples.csv` and visible in the dashboard.

## Limitations
1. **Everything is simulated, and I wrote the simulator.** Effects such as card type mattering little, the delayed-retry payoff and the hidden causes are my assumptions. The 72-cell router win depends on card type being a weak signal in this world; a real merchant may differ.
2. **The agent is a stub.** Claude's behaviour is unmeasured (no API key was available). The Claude client is unit-tested with a fake client only and has never run live. The stub's rules encode structure of the simulated world, so its scores overstate what a model without that knowledge would achieve. Token counts are estimates; latency is not measured.
3. **Delayed retries are free** apart from a 15% customer drop-off for non-recurring customers. That makes "retry after a delay" a strong default and shrinks any agent's headroom.
4. **One recovery attempt per decline**, no customer history dynamics, and `seconds_since_last_attempt` is always 0.
5. **Simplified taxonomy.** Specific hard codes are perfectly reliable here; real response codes are messier and card-network rules change.
6. **Baseline choice matters.** Static uses the best single PSP on this data (PSP_C). A weaker static choice would inflate every gain; the rule-based baseline uses coarse rules fitted on dev seeds.
7. **Narrow intervals.** Twelve seeds with common random numbers give very tight intervals. They capture seed variance, not model risk.
8. **Routing alone is a modest, slow-learning gain** at this volume (data-limited, see Phase 3), and it creates segment-level auth rate regressions unless paired with recovery. Whether to add an auth-rate floor to the objective is an open product question.
9. **The oracle is myopic**: it picks the PSP by first-attempt value and ignores expected recovery value.
