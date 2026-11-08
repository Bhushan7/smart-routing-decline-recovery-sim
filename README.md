# Smart Routing & Decline Recovery Simulator

A simulator that compares static payment routing against an adaptive (bandit) router, plus an agent that interprets decline codes and picks retry, cascade, delay, or stop.

**Status:** Phase 3b (adaptive router v2). Results on frozen eval seeds are in `evals/results/`; no agent yet. All numbers simulated.

All data is synthetic and all numbers will be labeled "simulated". The decline taxonomy is a simplified model, not card-network rules. See [PROJECT2_KICKOFF.md](PROJECT2_KICKOFF.md) for the plan and [docs/simulator-assumptions.md](docs/simulator-assumptions.md) for the proposed assumptions.

Quickstart, results, trade-offs and limitations will be added in Phase 6.
