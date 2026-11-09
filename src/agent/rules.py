"""Deterministic rules layer: handles the clear cases and defines the safe default.

Classification uses the response code only (what an operator sees). Hard codes always stop. Clear
technical codes cascade. Specific soft codes map to a sensible fixed action. Ambiguous codes are
the only ones the rules cannot settle, so they get a default action and, optionally, the agent.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..simulator.config import CASCADE, RETRY_DELAYED, RETRY_NOW, STOP
from ..simulator.types import Action, Transaction
from .observed import ObservedState

SOFT_RULES = {
    "SOFT_INSUFFICIENT_FUNDS": Action(RETRY_DELAYED, None, 86400),
    "SOFT_ISSUER_UNAVAILABLE": Action(RETRY_DELAYED, None, 600),
    "SOFT_AMOUNT_LIMIT": Action(STOP),
    "SOFT_VELOCITY": Action(RETRY_DELAYED, None, 3600),
    "SOFT_AUTH_REQUIRED": Action(STOP),
}
# Default for ambiguous codes when nothing smarter is available. Chosen on dev seeds (see
# docs/simulator-assumptions.md section 14), not on frozen eval seeds.
AMBIGUOUS_DEFAULT = "delayed"


@dataclass
class RuleDecision:
    klass: str  # hard | technical | soft | ambiguous
    confident: bool
    action: Action


class RulesLayer:
    def __init__(self, state: ObservedState, ambiguous_default: str = AMBIGUOUS_DEFAULT):
        self.state = state
        self.ambiguous_default = ambiguous_default

    @staticmethod
    def classify(code: str) -> str:
        if code.startswith("HARD_"):
            return "hard"
        if code.startswith("TECH_"):
            return "technical"
        if code.startswith("SOFT_"):
            return "soft"
        return "ambiguous"

    def decide(self, txn: Transaction, psp: int, code: str) -> RuleDecision:
        klass = self.classify(code)
        if klass == "hard":
            return RuleDecision(klass, True, Action(STOP))
        if klass == "technical":
            return RuleDecision(klass, True, Action(CASCADE, self.state.best_alternative_psp(psp)))
        if klass == "soft":
            return RuleDecision(klass, True, SOFT_RULES.get(code, Action(STOP)))
        return RuleDecision(klass, False, self.default_action(psp))

    def default_action(self, psp: int) -> Action:
        d = self.ambiguous_default
        if d == "now":
            return Action(RETRY_NOW)
        if d == "delayed":
            return Action(RETRY_DELAYED, None, 3600)
        if d == "cascade":
            return Action(CASCADE, self.state.best_alternative_psp(psp))
        return Action(STOP)

    def guard(self, code: str, action: Action) -> Action:
        """Hard guardrail, enforced in code: a code the rules classify as hard is never retried."""
        if self.classify(code) == "hard":
            return Action(STOP)
        return action
