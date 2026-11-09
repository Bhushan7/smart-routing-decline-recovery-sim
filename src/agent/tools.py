"""The four deterministic, read-only tools the agent may call."""
from __future__ import annotations

from ..simulator.config import ACTION_NAMES, CASCADE, PSPS
from ..simulator.types import Transaction
from .observed import ObservedState

SCHEMAS = [
    {"name": "get_decline_history",
     "description": "Decline history for this customer: how many recent declines they had (last 30 days).",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "get_segment_stats",
     "description": "Observed first-attempt approval rate and attempt count per PSP for this transaction's "
                    "segment. approval_rate is null when fewer than 20 attempts exist.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "get_psp_health",
     "description": "Recent approval rate, technical-error rate and a degraded flag for every PSP.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "estimate_retry_success",
     "description": "Estimated success probability and expected net value (simulated currency units, "
                    "after fees and retry cost) of one recovery action for this decline's response code. "
                    "For cascade, give target_psp.",
     "input_schema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": list(ACTION_NAMES[:3])},
         "target_psp": {"type": "string", "enum": list(PSPS)}},
         "required": ["action"], "additionalProperties": False}},
]


class ToolBox:
    def __init__(self, state: ObservedState):
        self.state = state
        self.txn: Transaction | None = None
        self.psp = 0
        self.code = ""
        self.calls = 0

    def bind(self, txn: Transaction, psp: int, code: str) -> None:
        self.txn, self.psp, self.code, self.calls = txn, psp, code, 0

    def call(self, name: str, args: dict | None = None) -> dict:
        """Execute a tool by name. Pure reads; never mutates simulator or router state."""
        args = args or {}
        self.calls += 1
        if name == "get_decline_history":
            return {"customer_recent_declines": self.txn.recent_declines}
        if name == "get_segment_stats":
            return {"segment_stats": self.state.segment_stats(self.txn)}
        if name == "get_psp_health":
            return {"psp_health": self.state.psp_health()}
        if name == "estimate_retry_success":
            if args.get("action") not in ACTION_NAMES[:3]:
                return {"error": "unknown action"}
            kind = ACTION_NAMES.index(args["action"])
            tgt = None
            if kind == CASCADE:
                if args.get("target_psp") not in PSPS or PSPS.index(args["target_psp"]) == self.psp:
                    return {"error": "cascade needs target_psp different from the current PSP"}
                tgt = PSPS.index(args["target_psp"])
            p, n = self.state.retry_estimate(self.code, kind)
            ev = self.state.expected_value(self.txn, self.psp, self.code, kind, tgt)
            return {"success_probability": round(p, 3), "observed_retries": n, "expected_net_value": round(ev, 3)}
        return {"error": f"unknown tool {name}"}
