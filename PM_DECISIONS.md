# PM Decisions

Filled progressively, completed in Phase 6.

## 1. Problem and user

## 2. Why now, why an agent

## 3. Scope cuts

## 4. Key trade-offs
### Approvals vs cost
### Exploration vs exploitation
Notes (Phase 3, adaptive router, all simulated):
- Algorithm: Thompson sampling on expected net value; Beta posterior on approval per (segment, PSP); fees known, approval learned.
- Backoff: segment -> (region, bin_group) -> global per PSP, prior strength capped at `prior_strength` pseudo-observations.
- Guardrails (not tuned, safety choices): per-PSP traffic cap 60% over a rolling 2,000-transaction window; uniform exploration floor.
- Tuned on dev seeds 1005-1007 (18-setting grid), checked on dev hold-out 1010-1012. Chosen: decay 0.999, prior_strength 5, explore_floor 0.01.
  Why: best on tuning seeds, second best on hold-out, and unlike decay 1.0 it can forget stale evidence after drift.
  Honest caveat: all settings sit within seed noise (about 0.4% spread in net value), so the choice is not strongly supported by the data.
- Phase 3b structure: learning hierarchy changed from 144 cells (backing off to 12) to a 12 -> 36 -> 72 chain that drops card_type from what the router learns (the simulator still has 144 segments and the guardrail still uses them). Chosen on dev seeds and confirmed on dev hold-out; reported on a fresh seed set (3000-3011) because the idea came partly from seeing the first frozen results.
- Caveat: dropping card_type works because the simulated card effect is small. In production that is an empirical question per merchant; the hierarchy is configurable for that reason.
- Cost of learning: the router is worse than static for roughly the first 30% of a run. At 300k transactions this learning cost eats most of the gain.
### Agent autonomy vs rules
Notes (Phase 4, all simulated, agent numbers are from the stub LLM, not Claude):
- Hard codes are never retried. This is enforced in code after the agent returns, and the agent is not even called for them.
- The agent is called only for ambiguous codes (about 30% of declines), with caching and a hard call cap; any invalid output, error or refusal falls back to the rules default and is logged. Cost: about 33 calls per 1,000 declines.
- Honest result so far: deterministic rules capture most of the value (about +3% net value, +2.5 auth points). A simple "delayed retry" default already captures 84.5% of the oracle value on ambiguous declines, so an agent's ceiling here is about 0.2% of net value. The stub agent added nothing measurable. Whether Claude adds value is untested (no API key available).
- Implication for the product case: lead with the rules layer and the guardrails; position the agent as a bounded add-on for the long tail, justified only if a real-model eval beats the rules default by more than its cost.

## 5. Success metrics
Results so far (Phase 5, simulated, 12 frozen seeds, agent = stub LLM): primary = net value per transaction (+3.5% vs static, 95% CI 3.5 to 3.6) and final auth rate (+2.54 points); secondary = soft-decline recovery (24.2%), retry efficiency (0.33 vs 0.87 for failover-only), regret vs oracle (-66% vs static), adaptation speed (median 5,864 region txns); guardrail = segment-level auth rate (adaptive routing alone leaves 41.5 of 144 segments worse than static, recovery brings it to 2.4), plus the agent ablation (agent minus rules-only = -0.003, no value).
Primary / secondary / guardrail (incl. segment-level: no segment worse while the average improves).

## 6. Risks and failure modes

## 7. Rollout path

## 8. What I would measure in production
