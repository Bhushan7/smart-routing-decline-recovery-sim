"""Measure the REAL Claude-backed agent on a small slice (needs ANTHROPIC_API_KEY; costs money).

  python evals/run_agent_claude.py --n 60000 --max-calls 600          # real Claude
  python evals/run_agent_claude.py --n 20000 --max-calls 100 --stub   # same code path, no API, no cost

Runs on a DEV seed. Compares: adaptive + rules-only vs adaptive + agent, on the same simulated stream.
All numbers are simulated. Tokens and latency are real when Claude is used and estimates for --stub.
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from src.agent.agent import AgentRecovery  # noqa: E402
from src.agent.llm import ClaudeLLM, StubLLM  # noqa: E402
from src.analysis import agent_eval, metrics  # noqa: E402
from src.routers.adaptive import AdaptiveParams, AdaptiveRouter  # noqa: E402
from src.simulator.config import SimConfig  # noqa: E402
from src.simulator.engine import run  # noqa: E402
from src.simulator.world import World  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60_000)
    ap.add_argument("--seed", type=int, default=1002)
    ap.add_argument("--max-calls", type=int, default=600)
    ap.add_argument("--stub", action="store_true")
    a = ap.parse_args()
    if not a.stub and not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. Set it, or pass --stub to check the code path without the API.")
        return 2
    cfg = SimConfig(n_txn=a.n)
    world = World(cfg, a.seed)
    out = {}
    for name, mode in (("adaptive_rules", "rules"), ("adaptive_agent", "agent")):
        llm = StubLLM() if a.stub else ClaudeLLM()
        rec = AgentRecovery(cfg, llm=llm, mode=mode, max_calls=a.max_calls)
        rng = np.random.default_rng(np.random.SeedSequence([a.seed, 77]))
        res = run(world, AdaptiveRouter(cfg, rng, AdaptiveParams.load()), rec)
        m = metrics.summarize(res)
        out[name] = {"net_value_per_txn": m["net_value_per_txn"], "auth_rate_final": m["auth_rate_final"]}
        if mode == "agent":
            lab = agent_eval.labeled_set(world, res)
            out[name]["decision_quality"] = agent_eval.decision_quality(lab)
            out[name]["cost"] = agent_eval.agent_cost(res)
            lab.to_csv(ROOT / "evals" / "results" / ("_stub_check.csv" if a.stub else "agent_claude_labeled.csv"),
                       index=False)
            out[name]["llm"] = llm.name
    print(json.dumps(out, indent=1, default=float))
    if not a.stub:
        (ROOT / "evals" / "results" / "agent_claude_summary.json").write_text(json.dumps(out, indent=1, default=float))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
