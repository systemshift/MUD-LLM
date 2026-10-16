from mudllm.agents.base import Decision, OutMessage
from mudllm.agents.greedy import GreedyIntentAgent
from mudllm.agents.providers import Completion, ToolCall, Usage
from mudllm.comms import make_router
from mudllm.comms.mediated import Mediated
from mudllm.control import Intent
from mudllm.games.bomberman import BombermanConfig, BombermanGame
from mudllm.loop import run_game


class FakeRelay:
    """Relays each message to member 3 only, as a digest; records what it was shown."""

    model = "fake"

    def __init__(self, target=3):
        self.target = target
        self.prompts = []

    def complete(self, instructions, items, tools, **kw):
        self.prompts.append(items[0]["content"])
        return Completion([ToolCall("d", "deliver", {"digests": [
            {"player": self.target, "text": "digest: P1 needs help at the north stones"},
            {"player": 99, "text": "not a member, must be dropped"}]})], "", "r",
            Usage(calls=1, input_tokens=500, output_tokens=50, cost_usd=0.001))


class Scripted(GreedyIntentAgent):
    def __init__(self, pid, cfg, plan):
        super().__init__(pid, cfg)
        self.plan, self.reports = plan, []

    def decide(self, obs, report):
        self.reports.append((obs.tick, report))
        return self.plan.get(obs.tick, Decision([Intent("wait", ticks=2)]))


def test_mediator_delivers_digests_not_raw_messages():
    cfg = BombermanConfig(num_players=4)
    relay = FakeRelay()
    plan = {0: Decision([Intent("wait", ticks=2)], [OutMessage("all", "help at north stones")],
                        focus="north stones")}
    agents = [Scripted(p, cfg, plan if p == 1 else {}) for p in range(1, 5)]
    router = Mediated(make_router("broadcast"), relay, name="mediator", period=3)
    result = run_game(BombermanGame(cfg, seed=1), agents, comms=router, max_ticks=12,
                      wake_on_message=False, heartbeat=2)
    raw = [m for _, r in agents[2].reports for m in r.messages if m.sender != 0]
    digests = [m for _, r in agents[2].reports for m in r.messages if m.sender == 0]
    assert not raw and digests and "north stones" in digests[0].text
    assert all(not r.messages for _, r in agents[1].reports)  # relay chose only P3
    assert result.log.of_kind("digest")[0].data["to"] == [3]
    assert "focus: north stones" in relay.prompts[0]  # sender's stated focus is in its profile
    assert result.comms["relay_calls"] >= 1 and result.comms["relay_cost_usd"] > 0


def test_mediated_hyperedges_only_relay_to_channel_members():
    from mudllm.comms import ChannelOp
    cfg = BombermanConfig(num_players=4)
    relay = FakeRelay(target=2)
    plans = {1: {0: Decision([Intent("wait", ticks=2)], [OutMessage("squad", "go north")],
                             channel_ops=[ChannelOp("create", "squad")])},
             2: {0: Decision([Intent("wait", ticks=2)],
                             channel_ops=[ChannelOp("join", "squad")])}}
    agents = [Scripted(p, cfg, plans.get(p, {})) for p in range(1, 5)]
    router = Mediated(make_router("self-organized"), relay, name="mediated-hyperedges", period=2)
    run_game(BombermanGame(cfg, seed=1), agents, comms=router, max_ticks=8,
             wake_on_message=False, heartbeat=2)
    assert "P2:" in relay.prompts[0] and "P3:" not in relay.prompts[0]  # roster = members
    assert any(m.sender == 0 for _, r in agents[1].reports for m in r.messages)


def test_agents_get_focus_field_for_smart_channels():
    from mudllm.agents.base import Report
    from mudllm.agents.llm_intent import LLMIntentAgent

    class P:
        model = "fake"

        def __init__(self):
            self.tools = []

        def complete(self, instructions, items, tools, **kw):
            self.tools.append(tools[0])
            return Completion([ToolCall("c", "give_orders", {"orders": []})], "", "r", Usage())

    provider = P()
    agent = LLMIntentAgent(1, BombermanConfig(), provider)
    agent.decide(BombermanGame(seed=1).observe(1),
                 Report("start", channels=["all"], comms_info="relayed", wants_focus=True))
    assert "focus" in provider.tools[0]["parameters"]["properties"]


def test_relay_remembers_history_and_reacts_to_new_needs():
    from mudllm.comms import Message
    relay = FakeRelay()
    router = Mediated(make_router("broadcast"), relay, period=1)

    class Ctx:
        def player_ids(self):
            return [1, 2, 3]

        def team(self, p):
            return 1

    ctx = Ctx()
    router.post(Message(1, 1, "all", "Oslo code is 4821"), ctx, {})
    router.flush(2, {1: "a", 2: "b", 3: "c"})
    assert "NEW [t1] P1: Oslo code is 4821" in relay.prompts[-1]
    assert router.flush(3, {1: "a", 2: "b", 3: "c"}) == []  # nothing new, nobody's needs changed
    router.flush(4, {1: "a", 2: "b", 3: "needs Oslo code"})  # P3's needs changed: relay again
    assert "[t1] P1: Oslo code is 4821" in relay.prompts[-1]  # earlier fact still available
    assert "NEW [t1]" not in relay.prompts[-1]
    assert "last digest you sent" in relay.prompts[-1]
