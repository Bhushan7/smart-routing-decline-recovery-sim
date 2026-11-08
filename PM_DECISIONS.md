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
- Cost of learning: the router is worse than static for roughly the first 30% of a run. At 300k transactions this learning cost eats most of the gain.
### Agent autonomy vs rules

## 5. Success metrics
Primary / secondary / guardrail (incl. segment-level: no segment worse while the average improves).

## 6. Risks and failure modes

## 7. Rollout path

## 8. What I would measure in production
