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

## Session 3: Phase 3 adaptive router
- Done: Thompson sampling router with hierarchical backoff, discounting, traffic cap, exploration floor; tuning on dev seeds only; one run on the frozen eval seeds; 8 new tests (27 total); adaptation chart and paired-difference tables.
- Result: adaptive beats static by +0.28% net value (10/12 seeds) but captures only ~10% of the oracle routing gap, lowers auth rate by 0.18 pts, and 50 segments are worse than static. Diagnosis in `docs/eval-report.md`.
- Next: Gate 3 decision (see open options in the PR).

## Session 4: Phase 3b (option B)
- Done: configurable learning hierarchy; compared 7 structures on dev seeds, confirmed on dev hold-out; added untouched seed set 3000-3011; one run of all strategies (plus v1 router for before/after).
- Result: adaptive v2 beats static by +0.75% net value in 12/12 seeds, captures 31% of the oracle routing gap (v1: 11%), auth rate no longer below static. Still 42 segments worse than static.
- Next: Gate 3 re-review. Phase 4 (decline-recovery agent) after approval.

## Session 5: Phase 4 decline recovery and agent
- Done: observable state, rules layer, four tools, LLM wrapper (Claude client + deterministic stub), agent with cache/cap/fallbacks/guardrail, rules-only ablation, static+rules strategy, labeled ambiguous-decline set, agent-vs-oracle eval, failure analysis, real-Claude eval script, 23 new tests (52 total), CI smoke now exercises the agent.
- Result (dev seeds, stub LLM only): rules recovery = +3% net value, +2.5 auth pts; stub agent = no gain over rules (-0.003, 0/5 seeds); agent ceiling is about 0.2% of net value.
- Blocker: no ANTHROPIC_API_KEY here, so Claude itself is unmeasured. The client is unit-tested with a fake client only.
- Next: Gate 4 decision.
