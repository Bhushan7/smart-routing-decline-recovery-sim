"""Agent-vs-oracle decision quality, agent cost, labeled set and failure cases. Simulated data."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..simulator.config import ACTION_NAMES, CASCADE, CAUSES, PSPS, STOP, cause_class
from ..simulator.engine import SimResult
from ..simulator.types import Action
from ..simulator.world import World

# Price used only for the cost ESTIMATE column (claude-opus-5-5 list price per million tokens).
PRICE_IN, PRICE_OUT = 4.0, 20.0


def _psp(j):
    return None if j is None else PSPS[j]


def _chosen(e: dict) -> Action:
    return Action(e["action"], e["target"], e["delay_s"])


def labeled_set(world: World, res: SimResult) -> pd.DataFrame:
    """Every ambiguous decline of a run, labeled with hidden cause and the oracle best action."""
    rec = res.recovery
    rows = []
    for e in rec.log:
        i, psp = e["idx"], e["psp"]
        cause = int(res.cause[i])
        best = world.best_action(i, psp, cause)
        chosen = _chosen(e)
        rd = Action(e["rule_default_kind"], e["rule_default_target"])
        ev_best = world.action_ev(i, psp, cause, best)
        ev_ch = world.action_ev(i, psp, cause, chosen)
        ev_rd = world.action_ev(i, psp, cause, rd)
        rows.append({
            "idx": i, "code": e["code"], "psp": PSPS[psp], "true_cause": CAUSES[cause],
            "true_class": cause_class(cause), "bin_group": int(world.bin[i]) + 1,
            "region": int(world.region[i]) + 1, "amount_band": int(world.amount[i]),
            "recurring": int(world.rec[i]), "recent_declines": int(world.recent[i]),
            "oracle_action": ACTION_NAMES[best.kind], "oracle_target": _psp(best.target_psp),
            "agent_action": ACTION_NAMES[chosen.kind], "agent_target": _psp(chosen.target_psp),
            "agent_confidence": e["confidence"], "source": e["source"], "explanation": e["explanation"],
            "kind_match": chosen.kind == best.kind,
            "exact_match": chosen.kind == best.kind
            and (chosen.kind != CASCADE or chosen.target_psp == best.target_psp),
            "ev_oracle": ev_best, "ev_agent": ev_ch, "ev_rules_default": ev_rd,
            "value_gap_agent": ev_best - ev_ch, "value_gap_rules_default": ev_best - ev_rd,
            "value_gap_stop": ev_best, "retried_hard": bool(chosen.kind != STOP and cause_class(cause) == "hard"),
        })
    return pd.DataFrame(rows)


def decision_quality(df: pd.DataFrame) -> dict:
    if df.empty:
        return {}
    by = df.groupby("true_class").exact_match.mean().round(3).to_dict()
    return {
        "n_ambiguous": len(df), "exact_match_rate": df.exact_match.mean(), "kind_match_rate": df.kind_match.mean(),
        "mean_value_gap_agent": df.value_gap_agent.mean(),
        "mean_value_gap_rules_default": df.value_gap_rules_default.mean(),
        "mean_value_gap_always_stop": df.value_gap_stop.mean(),
        "share_of_oracle_value_agent": 1 - df.value_gap_agent.sum() / df.value_gap_stop.sum(),
        "share_of_oracle_value_rules_default": 1 - df.value_gap_rules_default.sum() / df.value_gap_stop.sum(),
        "wasted_retries_on_hard": int(df.retried_hard.sum()), "exact_match_by_true_class": by,
    }


def agent_cost(res: SimResult) -> dict:
    r = res.recovery.report()
    declines, calls = max(1, r["declines"]), r["agent_calls"]
    usd = (r["input_tokens"] * PRICE_IN + r["output_tokens"] * PRICE_OUT) / 1e6
    return {
        "declines": r["declines"], "ambiguous": r["ambiguous"], "agent_calls": calls,
        "calls_per_1000_declines": 1000 * calls / declines,
        "call_rate_of_ambiguous": calls / max(1, r["ambiguous"]),
        "cache_hit_rate_of_ambiguous": r["cache_hits"] / max(1, r["ambiguous"]),
        "fallbacks": r["fallbacks_total"], "fallback_detail": r["fallbacks"],
        "input_tokens": r["input_tokens"], "output_tokens": r["output_tokens"],
        "tokens_are_estimates": r["tokens_estimated"],
        "avg_latency_s_per_call": r["latency_s"] / calls if calls else 0.0,
        "tool_calls_per_agent_call": r["tool_calls"] / calls if calls else 0.0,
        "est_usd_per_1000_declines_at_list_price": 1000 * usd / declines,
    }


def failure_cases(df: pd.DataFrame, k: int = 5) -> pd.DataFrame:
    """The k costliest bad decisions, one per distinct (true cause, agent action) pair."""
    bad = df[df.value_gap_agent > 0].sort_values("value_gap_agent", ascending=False)
    out, seen = [], set()
    for _, row in bad.iterrows():
        key = (row.true_cause, row.agent_action)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
        if len(out) == k:
            break
    return pd.DataFrame(out)


__all__ = ["labeled_set", "decision_quality", "agent_cost", "failure_cases", "np"]
