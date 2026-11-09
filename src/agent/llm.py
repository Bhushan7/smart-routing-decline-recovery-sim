"""LLM wrapper: one interface, a deterministic stub (tests, CI, demo) and a Claude implementation."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Protocol

from ..simulator.config import PSPS
from .tools import SCHEMAS, ToolBox


@dataclass
class LLMResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0
    tool_calls: int = 0
    estimated_tokens: bool = False  # True for the stub (character-count estimate, not real usage)


class LLM(Protocol):
    name: str

    def run(self, system: str, user: str, tools: ToolBox, max_turns: int = 6) -> LLMResult: ...


class StubLLM:
    """Deterministic stand-in so tests and CI need no API key and no cost.

    It reads the same tools a real model would and applies fixed, transparent rules of thumb. It is a
    plumbing check and a heuristic baseline, NOT a measurement of Claude. Its thresholds encode the
    qualitative structure I built into the simulated world, so its accuracy overstates what a
    general-purpose model would achieve with no knowledge of the simulator.
    """

    def __init__(self, variant: str = "v2"):
        assert variant in ("v1", "v2")
        self.variant = variant
        self.name = "stub" if variant == "v2" else "stub_v1"

    def run(self, system: str, user: str, tools: ToolBox, max_turns: int = 6) -> LLMResult:
        ctx = json.loads(user)
        txn, psp = tools.txn, tools.psp
        health = tools.call("get_psp_health")["psp_health"]
        hist = tools.call("get_decline_history")["customer_recent_declines"]
        out = self._decide(ctx, tools, psp, txn, health, hist, self.variant)
        text = json.dumps(out)
        return LLMResult(text, input_tokens=(len(system) + len(user)) // 4, output_tokens=len(text) // 4,
                         tool_calls=tools.calls, estimated_tokens=True)

    @staticmethod
    def _decide(ctx, tools, psp, txn, health, hist, variant="v2") -> dict:
        def best_other():
            c = [h for i, h in enumerate(health) if i != psp]
            c.sort(key=lambda h: (not h["degraded"], h["recent_approval_rate"] or 0), reverse=True)
            return c[0]["psp"]

        if health[psp]["degraded"]:
            return {"action": "cascade", "target_psp": best_other(), "delay_seconds": None, "confidence": 0.7,
                    "explanation": "The current PSP looks degraded, so an unclear decline is likely technical; "
                                   "retry on the healthiest other PSP."}
        if hist >= 2:
            return {"action": "retry_same_delayed", "target_psp": None, "delay_seconds": 3600, "confidence": 0.6,
                    "explanation": "Several recent declines on this customer suggest a velocity limit; retry later."}
        if ctx["segment"]["recurring"]:
            return {"action": "retry_same_delayed", "target_psp": None, "delay_seconds": 86400, "confidence": 0.55,
                    "explanation": "A recurring payment with an unclear decline is most often insufficient "
                                   "funds; retry after a day."}
        # v1 only: stop on large one-time amounts. Removed in v2 after dev-seed failure analysis, because
        # the payoff of a successful recovery grows with the amount, so stopping there is rarely right.
        if variant == "v1" and ctx["segment"]["amount_band"] == "high":
            return {"action": "stop", "target_psp": None, "delay_seconds": None, "confidence": 0.5,
                    "explanation": "A large one-time amount with an unclear decline often hits an amount limit; "
                                   "a retry is unlikely to pay for itself."}
        best, best_ev = None, 0.0
        for action, tgt in (("retry_same_now", None), ("retry_same_delayed", None), ("cascade", best_other())):
            args = {"action": action, **({"target_psp": tgt} if tgt else {})}
            ev = tools.call("estimate_retry_success", args).get("expected_net_value", -1.0)
            if ev > best_ev:
                best, best_ev = (action, tgt), ev
        if best is None:
            return {"action": "stop", "target_psp": None, "delay_seconds": None, "confidence": 0.5,
                    "explanation": "No recovery action has a positive expected net value."}
        action, tgt = best
        ev = best_ev
        return {"action": action, "target_psp": tgt, "delay_seconds": 600 if action == "retry_same_delayed" else None,
                "confidence": 0.4, "explanation": f"Best estimated expected net value is {ev:.2f} for {action}."}


class ClaudeLLM:
    """Claude implementation (Anthropic SDK). Reads ANTHROPIC_API_KEY from the environment.

    Not exercised live in this repo's CI. Opus 5.5 notes: thinking cannot be disabled (effort is the
    control, set low here), forced tool_choice is not allowed (we use auto), sampling params are not set.
    """

    def __init__(self, model: str | None = None, client=None, max_tokens: int = 1024, effort: str = "low"):
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-opus-5-5")
        self.name = self.model
        self.max_tokens = max_tokens
        self.effort = effort
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self.client = client

    def run(self, system: str, user: str, tools: ToolBox, max_turns: int = 6) -> LLMResult:
        messages = [{"role": "user", "content": user}]
        t0 = time.perf_counter()
        tin = tout = ncalls = 0
        text = ""
        for _ in range(max_turns):
            resp = self.client.messages.create(
                model=self.model, max_tokens=self.max_tokens, system=system, tools=SCHEMAS,
                messages=messages, output_config={"effort": self.effort},
            )
            tin += resp.usage.input_tokens
            tout += resp.usage.output_tokens
            if resp.stop_reason == "refusal":
                text = ""
                break
            if resp.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": resp.content})  # keep thinking blocks intact
                results = []
                for block in resp.content:
                    if block.type == "tool_use":
                        ncalls += 1
                        out = tools.call(block.name, dict(block.input))
                        results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(out),
                                        **({"is_error": True} if "error" in out else {})})
                messages.append({"role": "user", "content": results})  # all results in one message
                continue
            text = "".join(b.text for b in resp.content if b.type == "text")
            break
        return LLMResult(text, tin, tout, time.perf_counter() - t0, ncalls)


def parse_decision(text: str, psp: int):
    """Parse and validate model output. Returns (Action, confidence, explanation) or raises ValueError."""
    from ..simulator.config import ACTION_NAMES, CASCADE, RETRY_DELAYED
    from ..simulator.types import Action

    try:
        start, end = text.index("{"), text.rindex("}") + 1
        obj = json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError) as e:
        raise ValueError(f"unparseable: {e}") from e
    if obj.get("action") not in ACTION_NAMES:
        raise ValueError("invalid action")
    kind = ACTION_NAMES.index(obj["action"])
    conf = obj.get("confidence")
    if not isinstance(conf, int | float) or isinstance(conf, bool) or not 0 <= conf <= 1:
        raise ValueError("invalid confidence")
    target, delay = None, 0
    if kind == CASCADE:
        if obj.get("target_psp") not in PSPS:
            raise ValueError("cascade without valid target_psp")
        target = PSPS.index(obj["target_psp"])
        if target == psp:
            raise ValueError("cascade to the same PSP")
    if kind == RETRY_DELAYED:
        d = obj.get("delay_seconds")
        if not isinstance(d, int) or isinstance(d, bool) or not 0 <= d <= 7 * 86400:
            raise ValueError("invalid delay_seconds")
        delay = d
    return Action(kind, target, delay), float(conf), str(obj.get("explanation", ""))[:500]
