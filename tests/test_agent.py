import json
from types import SimpleNamespace

import numpy as np
import pytest

from src.agent.agent import AgentRecovery
from src.agent.llm import ClaudeLLM, LLMResult, StubLLM, parse_decision
from src.agent.observed import ObservedState
from src.agent.rules import RulesLayer
from src.routers.adaptive import AdaptiveParams, AdaptiveRouter
from src.simulator.config import CASCADE, HARD_CAUSES, RETRY_DELAYED, RETRY_NOW, STOP, SimConfig
from src.simulator.engine import run
from src.simulator.types import Action, RouterState, Transaction
from src.simulator.world import World

CFG = SimConfig(n_txn=30_000)
ST = RouterState(0, 1000)


def txn(i=1, rec=0, amount=1, recent=0, region=0, seg=5):
    return Transaction(i, 0, 0, region, amount, rec, 12, 1, recent, seg)


class ScriptedLLM:
    """Returns a fixed text; counts calls."""

    name = "scripted"

    def __init__(self, text):
        self.text, self.calls = text, 0

    def run(self, system, user, tools, max_turns=6):
        self.calls += 1
        return LLMResult(self.text if isinstance(self.text, str) else self.text(user), 10, 5)


def good(action="retry_same_now", **kw):
    return json.dumps({"action": action, "target_psp": None, "delay_seconds": None, "confidence": 0.5,
                       "explanation": "x", **kw})


# ---------------- rules layer
def test_rules_hard_always_stop_and_confident():
    r = RulesLayer(ObservedState(CFG))
    for code in ("HARD_STOLEN_CARD", "HARD_INVALID_CARD", "HARD_CLOSED_ACCOUNT", "HARD_FRAUD_SUSPECTED"):
        d = r.decide(txn(), 2, code)
        assert d.klass == "hard" and d.confident and d.action.kind == STOP


def test_rules_technical_cascades_to_other_psp():
    r = RulesLayer(ObservedState(CFG))
    for code in ("TECH_PSP_TIMEOUT", "TECH_NETWORK_ERROR", "TECH_PSP_DEGRADED"):
        d = r.decide(txn(), 2, code)
        assert d.confident and d.action.kind == CASCADE and d.action.target_psp != 2


def test_rules_soft_codes_map_and_ambiguous_is_not_confident():
    r = RulesLayer(ObservedState(CFG))
    assert r.decide(txn(), 2, "SOFT_INSUFFICIENT_FUNDS").action.kind == RETRY_DELAYED
    assert r.decide(txn(), 2, "SOFT_AMOUNT_LIMIT").action.kind == STOP
    for code in ("AMBIGUOUS_GENERIC_DECLINE", "AMBIGUOUS_DO_NOT_HONOR"):
        d = r.decide(txn(), 2, code)
        assert not d.confident and d.klass == "ambiguous"


def test_guard_forces_stop_for_hard_codes_in_code():
    r = RulesLayer(ObservedState(CFG))
    for a in (Action(RETRY_NOW), Action(RETRY_DELAYED, None, 60), Action(CASCADE, 1)):
        assert r.guard("HARD_STOLEN_CARD", a).kind == STOP
        assert r.guard("AMBIGUOUS_GENERIC_DECLINE", a) == a


# ---------------- selective calling and guardrails
def test_agent_not_called_for_clear_codes_even_if_it_would_retry_everything():
    llm = ScriptedLLM(good("retry_same_now"))
    ag = AgentRecovery(CFG, llm=llm)
    for code in ("HARD_STOLEN_CARD", "TECH_PSP_TIMEOUT", "SOFT_VELOCITY", "SOFT_AMOUNT_LIMIT"):
        ag.decide(txn(), 2, code, ST)
    assert llm.calls == 0
    assert ag.decide(txn(), 2, "HARD_FRAUD_SUSPECTED", ST).kind == STOP


def test_agent_called_for_ambiguous_and_decision_logged():
    llm = ScriptedLLM(good("retry_same_delayed", delay_seconds=3600))
    ag = AgentRecovery(CFG, llm=llm)
    a = ag.decide(txn(), 2, "AMBIGUOUS_GENERIC_DECLINE", ST)
    assert a.kind == RETRY_DELAYED and a.delay_s == 3600 and llm.calls == 1
    assert ag.log[-1]["source"] == "agent" and ag.log[-1]["explanation"] == "x"


@pytest.mark.parametrize("bad", [
    "not json at all",
    json.dumps({"action": "teleport", "confidence": 0.5}),
    json.dumps({"action": "cascade", "target_psp": "PSP_C", "confidence": 0.5}),  # same PSP as current (2)
    json.dumps({"action": "cascade", "target_psp": None, "confidence": 0.5}),
    json.dumps({"action": "stop", "confidence": 7}),
    json.dumps({"action": "retry_same_delayed", "delay_seconds": -5, "confidence": 0.5}),
    "",
])
def test_invalid_output_falls_back_to_rules_default_and_is_logged(bad):
    ag = AgentRecovery(CFG, llm=ScriptedLLM(bad))
    a = ag.decide(txn(), 2, "AMBIGUOUS_DO_NOT_HONOR", ST)
    assert a == ag.rules.default_action(2)
    assert ag.stats.fallbacks["invalid_output"] == 1
    assert ag.log[-1]["source"] == "fallback:invalid_output"


def test_llm_exception_falls_back_and_never_crashes():
    class Boom:
        name = "boom"

        def run(self, *a, **k):
            raise RuntimeError("network down")

    ag = AgentRecovery(CFG, llm=Boom())
    assert ag.decide(txn(), 2, "AMBIGUOUS_GENERIC_DECLINE", ST) == ag.rules.default_action(2)
    assert ag.stats.fallbacks["llm_error"] == 1


def test_cache_reuses_identical_contexts_and_distinguishes_different_ones():
    llm = ScriptedLLM(good("stop"))
    ag = AgentRecovery(CFG, llm=llm)
    for i in range(5):
        ag.decide(txn(i), 2, "AMBIGUOUS_GENERIC_DECLINE", ST)
    assert llm.calls == 1 and ag.stats.cache_hits == 4
    ag.decide(txn(9, rec=1), 2, "AMBIGUOUS_GENERIC_DECLINE", ST)  # different context bucket
    ag.decide(txn(10), 2, "AMBIGUOUS_DO_NOT_HONOR", ST)  # different code
    assert llm.calls == 3


def test_call_cap_enforced_and_logged():
    llm = ScriptedLLM(good("stop"))
    ag = AgentRecovery(CFG, llm=llm, max_calls=2)
    for k, region in enumerate((0, 1, 2, 0)):
        ag.decide(txn(k, region=region, rec=k % 2), 2, "AMBIGUOUS_GENERIC_DECLINE", ST)
    assert llm.calls == 2 and ag.stats.fallbacks["call_cap"] >= 1


def test_rules_mode_never_calls_the_llm():
    llm = ScriptedLLM(good("stop"))
    ag = AgentRecovery(CFG, llm=llm, mode="rules")
    ag.decide(txn(), 2, "AMBIGUOUS_GENERIC_DECLINE", ST)
    assert llm.calls == 0 and ag.log[-1]["source"] == "rules_default"


# ---------------- stub and parsing
def test_stub_llm_is_deterministic():
    def go():
        ag = AgentRecovery(CFG, llm=StubLLM())
        return [ag.decide(txn(i, rec=i % 2, recent=i % 4), 2, "AMBIGUOUS_GENERIC_DECLINE", ST) for i in range(12)]

    assert go() == go()


def test_parse_decision_accepts_text_around_json():
    a, conf, expl = parse_decision('Sure:\n{"action": "stop", "confidence": 0.9, "explanation": "e"}\n', 2)
    assert a.kind == STOP and conf == 0.9 and expl == "e"


# ---------------- Claude implementation with a fake client (no network)
def _resp(blocks, stop, tin=100, tout=20):
    usage = SimpleNamespace(input_tokens=tin, output_tokens=tout)
    return SimpleNamespace(content=blocks, stop_reason=stop, usage=usage)


class FakeClient:
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.requests.append(kw)
        return self.responses.pop(0)


def test_claude_tool_loop_executes_tools_and_sums_usage():
    tool_use = SimpleNamespace(type="tool_use", id="t1", name="get_psp_health", input={})
    final = SimpleNamespace(type="text", text=good("stop"))
    client = FakeClient([_resp([tool_use], "tool_use"), _resp([final], "end_turn")])
    llm = ClaudeLLM(model="claude-opus-5-5", client=client)
    ag = AgentRecovery(CFG, llm=llm)
    a = ag.decide(txn(), 2, "AMBIGUOUS_GENERIC_DECLINE", ST)
    assert a.kind == STOP
    assert ag.stats.input_tokens == 200 and ag.stats.output_tokens == 40 and ag.stats.tool_calls == 1
    second = client.requests[1]["messages"]
    assert second[-1]["role"] == "user" and second[-1]["content"][0]["type"] == "tool_result"
    assert all("tool_choice" not in r and "temperature" not in r for r in client.requests)


def test_claude_refusal_falls_back():
    client = FakeClient([_resp([], "refusal")])
    ag = AgentRecovery(CFG, llm=ClaudeLLM(client=client))
    assert ag.decide(txn(), 2, "AMBIGUOUS_GENERIC_DECLINE", ST) == ag.rules.default_action(2)
    assert ag.stats.fallbacks["invalid_output"] == 1


# ---------------- end to end
def test_end_to_end_run_never_retries_specific_hard_codes_and_logs():
    world = World(CFG, 1000)
    ag = AgentRecovery(CFG, llm=StubLLM())
    router = AdaptiveRouter(CFG, np.random.default_rng(3), AdaptiveParams.load())
    res = run(world, router, ag, n=25_000)
    for i in np.where(res.retried)[0]:
        if res.cause[i] in HARD_CAUSES:
            assert world.observed_code(int(i), int(res.cause[i])).startswith("AMBIGUOUS_")
    r = ag.report()
    assert r["declines"] == int((res.cause >= 0).sum()) and r["rule_handled"] + r["ambiguous"] == r["declines"]
    assert r["agent_calls"] + r["cache_hits"] + r["fallbacks_total"] == r["ambiguous"]
    assert r["cache_hits"] > r["agent_calls"]  # the cache serves most ambiguous declines even in a short run


def test_retry_outcomes_feed_the_observable_estimator():
    world = World(CFG, 1000)
    ag = AgentRecovery(CFG, llm=StubLLM(), mode="rules")
    run(world, AdaptiveRouter(CFG, np.random.default_rng(3), AdaptiveParams.load()), ag, n=15_000)
    assert sum(n for _, n in ag.state.retry.values()) > 0
