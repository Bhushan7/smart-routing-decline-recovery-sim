"""Decline-recovery recovery policy: rules first, agent only for ambiguous declines.

Cost controls: the agent is called only when the rules cannot classify with confidence, identical
(code, PSP, segment bucket, context bucket) decisions are cached, and a per-run call cap applies.
Guardrails: hard codes are never retried (enforced in code, after the agent returns); any invalid
output or error falls back to the rules default, and every fallback is logged with its reason.
"""
from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass, field

from ..simulator.config import ACTION_NAMES, AMOUNT_BANDS, PSPS, SimConfig
from ..simulator.types import Action, Outcome, RouterState, Transaction
from .llm import LLM, StubLLM, parse_decision
from .observed import ObservedState
from .prompts import SYSTEM_PROMPT
from .rules import RulesLayer
from .tools import ToolBox

CACHE_TTL_TXNS = 60_000


@dataclass
class AgentStats:
    declines: int = 0
    rule_handled: int = 0
    ambiguous: int = 0
    agent_calls: int = 0
    cache_hits: int = 0
    fallbacks: Counter = field(default_factory=Counter)
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0
    tool_calls: int = 0
    tokens_estimated: bool = False

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "fallbacks"}
        d["fallbacks"] = dict(self.fallbacks)
        d["fallbacks_total"] = sum(self.fallbacks.values())
        return d


class AgentRecovery:
    """Implements the RecoveryPolicy protocol. mode='rules' is the rules-only ablation."""

    def __init__(self, cfg: SimConfig, llm: LLM | None = None, mode: str = "agent",
                 max_calls: int | None = None, ambiguous_default: str | None = None):
        assert mode in ("agent", "rules")
        self.cfg = cfg
        self.mode = mode
        self.llm = llm or StubLLM()
        self.max_calls = max_calls if max_calls is not None else int(os.environ.get("AGENT_MAX_CALLS", "5000"))
        self.state = ObservedState(cfg)
        kw = {} if ambiguous_default is None else {"ambiguous_default": ambiguous_default}
        self.rules = RulesLayer(self.state, **kw)
        self.tools = ToolBox(self.state)
        self.cache: dict[tuple, tuple[Action, float, str, int]] = {}
        self.stats = AgentStats()
        self.log: list[dict] = []  # ambiguous declines only: decisions, with explanations

    # ---- hooks called by the engine
    def observe_attempt(self, txn: Transaction, psp: int, outcome: Outcome) -> None:
        self.state.observe_attempt(txn, psp, outcome)

    def observe_retry(self, txn: Transaction, psp: int, code: str, action: Action, ok: bool) -> None:
        self.state.observe_retry(code, action.kind, ok)

    # ---- decision
    def decide(self, txn: Transaction, psp: int, code: str, state: RouterState) -> Action:
        st = self.stats
        st.declines += 1
        rd = self.rules.decide(txn, psp, code)
        if rd.confident:
            st.rule_handled += 1
            return self.rules.guard(code, rd.action)
        st.ambiguous += 1
        action, conf, expl, source = rd.action, 0.0, "rules default", "rules_default"
        if self.mode == "agent":
            action, conf, expl, source = self._agent(txn, psp, code, state, rd.action)
        action = self.rules.guard(code, action)
        self.log.append({"idx": txn.idx, "psp": psp, "code": code, "source": source,
                         "action": action.kind, "target": action.target_psp, "delay_s": action.delay_s,
                         "confidence": conf, "explanation": expl, "rule_default_kind": rd.action.kind,
                         "rule_default_target": rd.action.target_psp})
        return action

    def _agent(self, txn, psp, code, state, default: Action):
        st = self.stats
        key = (code, psp, txn.recurring, txn.amount_band, txn.region, min(txn.recent_declines, 2),
               self.state.is_degraded(psp))
        hit = self.cache.get(key)
        if hit and state.t - hit[3] <= CACHE_TTL_TXNS:
            st.cache_hits += 1
            return hit[0], hit[1], hit[2], "cache"
        if st.agent_calls >= self.max_calls:
            st.fallbacks["call_cap"] += 1
            return default, 0.0, "call cap reached", "fallback:call_cap"
        user = self._user_message(txn, psp, code)
        self.tools.bind(txn, psp, code)
        st.agent_calls += 1
        try:
            res = self.llm.run(SYSTEM_PROMPT, user, self.tools)
        except Exception as e:  # network, auth, SDK errors: never crash the run
            st.fallbacks["llm_error"] += 1
            return default, 0.0, f"llm error: {type(e).__name__}", "fallback:llm_error"
        st.input_tokens += res.input_tokens
        st.output_tokens += res.output_tokens
        st.latency_s += res.latency_s
        st.tool_calls += res.tool_calls
        st.tokens_estimated = st.tokens_estimated or res.estimated_tokens
        try:
            action, conf, expl = parse_decision(res.text, psp)
        except ValueError as e:
            st.fallbacks["invalid_output"] += 1
            return default, 0.0, f"invalid output: {e}", "fallback:invalid_output"
        self.cache[key] = (action, conf, expl, state.t)
        return action, conf, expl, "agent"

    def _user_message(self, txn: Transaction, psp: int, code: str) -> str:
        import json

        return json.dumps({
            "response_code": code, "current_psp": PSPS[psp],
            "segment": {"bin_group": f"BIN_GROUP_{txn.bin_group + 1}", "card_type": ("debit", "credit")[txn.card_type],
                        "region": f"REGION_{txn.region + 1}", "amount_band": AMOUNT_BANDS[txn.amount_band],
                        "recurring": bool(txn.recurring)},
            "hour_of_day": txn.hour, "seconds_since_last_attempt": 0,
            "note": "Use the tools for decline history, segment stats, PSP health and retry estimates.",
        })

    def report(self) -> dict:
        d = self.stats.to_dict()
        d.update(mode=self.mode, llm=self.llm.name, max_calls=self.max_calls)
        return d


__all__ = ["AgentRecovery", "AgentStats", "ACTION_NAMES"]
