import pytest

from mudllm.agents.base import Report
from mudllm.agents.greedy import GreedyIntentAgent
from mudllm.agents.llm_intent import LLMIntentAgent
from mudllm.agents.providers import Completion, ToolCall, Usage
from mudllm.control import Intent, Outcome
from mudllm.games.bomberman import BombermanConfig, BombermanGame
from mudllm.loop import Clock, run_game

CFG = BombermanConfig()


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_greedy_intent_agent_clears_boards_safely(seed):
    result = run_game(BombermanGame(CFG, seed=seed), [GreedyIntentAgent(1, CFG)])
    assert result.cleared
    assert result.players[1]["hits"] == 0


def test_thinking_time_costs_ticks():
    fast = run_game(BombermanGame(CFG, seed=1), [GreedyIntentAgent(1, CFG)], max_ticks=150)
    slow = run_game(BombermanGame(CFG, seed=1), [GreedyIntentAgent(1, CFG)],
                    Clock(think_ticks=10), max_ticks=150)
    assert slow.players[1]["idle_ticks"] > fast.players[1]["idle_ticks"]
    assert slow.game["stones_remaining"] > fast.game["stones_remaining"]


def test_multiplayer_runs_with_simultaneous_agents():
    cfg = BombermanConfig(num_players=4)
    agents = [GreedyIntentAgent(pid, cfg) for pid in range(1, 5)]
    result = run_game(BombermanGame(cfg, seed=3), agents, max_ticks=300)
    assert result.cleared
    assert sum(p["score"] for p in result.players.values()) > 0


def test_decisions_are_logged():
    result = run_game(BombermanGame(CFG, seed=1), [GreedyIntentAgent(1, CFG)], max_ticks=30)
    decisions = result.log.of_kind("decision")
    assert decisions and decisions[0].data["player"] == 1


# ---------------------------------------------------------------- LLM plumbing


class FakeProvider:
    """Returns scripted tool calls and records what it was sent."""

    model = "fake"

    def __init__(self, scripted: list[list[ToolCall]]):
        self.scripted = scripted
        self.requests: list[dict] = []
        self.tools: list[dict] = []

    def complete(self, instructions, input_items, tools, previous_response_id=None, **kw):
        n = len(self.requests)
        self.requests.append({"items": input_items, "previous": previous_response_id})
        self.tools.append(tools[0])
        calls = self.scripted[min(n, len(self.scripted) - 1)]
        return Completion(calls, "", f"resp_{n}", Usage(calls=1, input_tokens=100))


def orders(*items):
    return [{"action": a, "row": r, "col": c, "ticks": t, "why": ""} for a, r, c, t in items]


def test_llm_intent_agent_returns_tool_results_on_next_turn():
    provider = FakeProvider([
        [ToolCall("c1", "give_orders", {"orders": orders(("bomb_at", 1, 3, 0),
                                                          ("goto", 1, 1, 0))})],
        [ToolCall("c2", "give_orders", {"orders": orders(("wait", 0, 0, 2))})],
    ])
    agent = LLMIntentAgent(1, CFG, provider, memory=True)
    obs = BombermanGame(CFG, seed=1).observe(1)

    intents = agent.decide(obs, Report("start")).intents
    assert [i.kind for i in intents] == ["bomb_at", "goto"]
    assert intents[0].target == (1, 3) and intents[0].ref == "c1"

    outcomes = [Outcome(intents[0], "done", "bomb placed", 5),
                Outcome(intents[1], "failed", "no path", 6)]
    agent.decide(obs, Report("an order failed", outcomes))
    second = provider.requests[1]
    assert second["previous"] == "resp_0"
    outputs = [i for i in second["items"] if i.get("type") == "function_call_output"]
    assert len(outputs) == 1 and outputs[0]["call_id"] == "c1"
    assert "done (bomb placed)" in outputs[0]["output"]
    assert "failed (no path)" in outputs[0]["output"]
    assert agent.usage.calls == 2


def test_llm_intent_agent_reports_running_orders_and_late_results():
    provider = FakeProvider([
        [ToolCall("c1", "give_orders", {"orders": orders(("goto", 1, 5, 0))})],
        [ToolCall("c2", "give_orders", {"orders": orders(("wait", 0, 0, 1))})],
        [ToolCall("c3", "give_orders", {"orders": orders(("wait", 0, 0, 1))})],
    ])
    agent = LLMIntentAgent(1, CFG, provider)
    obs = BombermanGame(CFG, seed=1).observe(1)
    first = agent.decide(obs, Report("start")).intents
    agent.decide(obs, Report("your last order is in progress"))
    assert "still running" in provider.requests[1]["items"][0]["output"]
    agent.decide(obs, Report("all orders complete", [Outcome(first[0], "done", "arrived", 9)]))
    assert "Results of earlier orders" in provider.requests[2]["items"][-1]["content"]


def test_llm_intent_agent_caps_orders():
    many = orders(*[("wait", 0, 0, 1)] * 7)
    provider = FakeProvider([[ToolCall("c1", "give_orders", {"orders": many})]])
    agent = LLMIntentAgent(1, CFG, provider)
    decision = agent.decide(BombermanGame(CFG, seed=1).observe(1), Report("start"))
    assert len(decision.intents) == 4


def test_llm_intent_agent_without_memory_inlines_results():
    call = ToolCall("c1", "give_orders", {"orders": orders(("wait", 0, 0, 1))})
    provider = FakeProvider([[call]])
    agent = LLMIntentAgent(1, CFG, provider, memory=False)
    obs = BombermanGame(CFG, seed=1).observe(1)
    intents = agent.decide(obs, Report("start")).intents
    agent.decide(obs, Report("all orders complete", [Outcome(intents[0], "done", "ok", 1)]))
    second = provider.requests[1]
    assert second["previous"] is None
    assert "Results of your last orders" in second["items"][0]["content"]


def test_llm_intent_agent_survives_provider_errors():
    class Broken:
        model = "broken"

        def complete(self, *a, **kw):
            raise RuntimeError("boom")

    agent = LLMIntentAgent(1, CFG, Broken())
    decision = agent.decide(BombermanGame(CFG, seed=1).observe(1), Report("start"))
    assert decision.intents == [Intent("wait", ticks=1)]
    assert agent.usage.errors == 1


class RecordingAgent(GreedyIntentAgent):
    def __init__(self, *a):
        super().__init__(*a)
        self.reasons = []

    def decide(self, obs, report):
        self.reasons.append(report.reason)
        return super().decide(obs, report)


def test_prefetch_wakes_when_last_order_starts():
    agent = RecordingAgent(1, CFG)
    run_game(BombermanGame(CFG, seed=1), [agent], Clock(think_ticks=5), max_ticks=60)
    assert any("in progress" in r for r in agent.reasons)

    agent = RecordingAgent(1, CFG)
    run_game(BombermanGame(CFG, seed=1), [agent], Clock(think_ticks=0), max_ticks=60)
    assert not any("in progress" in r for r in agent.reasons)


def test_llm_agent_tool_gets_comms_fields_only_with_channels():
    provider = FakeProvider([[ToolCall("c1", "give_orders", {
        "orders": orders(("wait", 0, 0, 1)),
        "messages": [{"channel": "team", "text": "I take the north stones"}],
        "keep_current_orders": True,
    })]])
    agent = LLMIntentAgent(1, CFG, provider)
    obs = BombermanGame(CFG, seed=1).observe(1)
    decision = agent.decide(obs, Report("start", channels=["team"], comms_info="Team chat."))
    assert decision.messages[0].text == "I take the north stones"
    assert decision.replace is False
    sent_tool = provider.tools[-1]
    assert "messages" in sent_tool["parameters"]["properties"]
    assert "COMMS: Team chat." in provider.requests[-1]["items"][-1]["content"]

    agent.decide(obs, Report("all orders complete"))
    assert "messages" not in provider.tools[-1]["parameters"]["properties"]


def test_llm_agent_sees_inbox():
    from mudllm.comms import Message
    call = ToolCall("c1", "give_orders", {"orders": orders(("wait", 0, 0, 1))})
    provider = FakeProvider([[call]])
    agent = LLMIntentAgent(1, CFG, provider)
    report = Report("new messages", messages=[Message(3, 2, "team", "help at row 5")],
                    channels=["team"], comms_info="Team chat.")
    agent.decide(BombermanGame(CFG, seed=1).observe(1), report)
    assert "P2 on team: help at row 5" in provider.requests[-1]["items"][-1]["content"]


def test_call_cost_uses_cached_and_long_context_rates():
    from mudllm.agents.providers.base import call_cost
    # 200k input of which 180k cached, 10k output on luna (short-context rates)
    assert call_cost("gpt-6-luna", 200_000, 180_000, 10_000) == pytest.approx(
        (20_000 * 0.125 + 180_000 * 0.01 + 10_000 * 0.5) / 1e6)
    short = call_cost("gpt-6-luna", 272_000, 0, 0)
    long = call_cost("gpt-6-luna", 272_001, 0, 0)
    assert long > 1.9 * short
    assert call_cost("unknown-model", 1000, 0, 1000) == 0.0
