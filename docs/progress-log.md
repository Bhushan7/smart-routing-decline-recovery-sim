# Progress log

## Session 1: Phase 1 setup
- Done: repo skeleton, Makefile, CI (ruff, pytest, eval smoke), draft assumptions doc, PM_DECISIONS template.
- Next: Gate 1 review of `docs/simulator-assumptions.md`. No simulator code until approved.
- Gate 1 answers recorded in the assumptions doc (sections 10-11). Volume 300k, 144 segments kept (Q8 resolved).

## Session 2: Phase 2 simulator, oracle, baselines
- Done: seeded world (traffic, hidden approval truth, drift + partial recovery, incident window, decline causes, retry truth), engine, routers (static, rule-based, oracle routing, oracle), recovery policies, metrics, multi-seed runner, `evals/seeds.json`, 19 tests, baseline chart on 5 dev seeds.
- Found: original margins (1/3/8) made PSP_A the best choice for 95% of traffic; changed to 3/12/45 (documented in assumptions doc, flagged for Gate 2).
- Found: static routing (primary PSP_C) is not affected by the drift on PSP_B; only the rule-based router degrades. Static falls behind the oracle but not because of the drift.
- Next: Gate 2 review. Phase 3 (adaptive router) only after approval.
