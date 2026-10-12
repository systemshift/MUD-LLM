from mudllm.agents.base import Decision, OutMessage, Report
from mudllm.agents.greedy import GreedyIntentAgent
from mudllm.agents.llm_intent import LLMIntentAgent
from mudllm.agents.providers import Completion, ToolCall, Usage
from mudllm.comms import ChannelOp, make_router
from mudllm.control import Intent
from mudllm.games.bomberman import BombermanConfig, BombermanGame
from mudllm.loop import run_game


class Ctx:
    """Six players, teams {1,2,3} and {4,5,6}; oracle edges per team."""

    def player_ids(self):
        return [1, 2, 3, 4, 5, 6]

    def team(self, pid):
        return 1 if pid <= 3 else 2

    def distance(self, a, b):
        return abs(a - b)

    def hyperedges(self):
        return {"north": {1, 2}, "south": {2, 3}, "east": {4, 5, 6}}

    def describe_player(self, pid):
        return f"P{pid}"


CTX = Ctx()


# ---------------------------------------------------------------- simple routers


def test_team_scope_never_crosses_teams():
    assert make_router("broadcast", scope="team").route(1, "all", "x", CTX, {}) == [2, 3]
    assert make_router("broadcast").route(1, "all", "x", CTX, {}) == [2, 3, 4, 5, 6]
    for _ in range(20):
        got = make_router("random-k", k=5, scope="team").route(4, "random", "x", CTX, {})
        assert set(got) <= {5, 6}


def test_random_k_audience_size_and_determinism():
    a = make_router("random-k", k=3, seed=7)
    b = make_router("random-k", k=3, seed=7)
    runs_a = [a.route(1, "random", "x", CTX, {}) for _ in range(5)]
    runs_b = [b.route(1, "random", "x", CTX, {}) for _ in range(5)]
    assert runs_a == runs_b
    assert all(len(r) == 3 and 1 not in r for r in runs_a)
    assert len({tuple(r) for r in runs_a}) > 1  # different recipients each time


def test_shuffled_hypergraph_keeps_sizes_but_changes_members():
    oracle = make_router("hypergraph").edges(CTX)
    shuffled = make_router("shuffled-hypergraph", seed=3).edges(CTX)
    assert {k: len(v) for k, v in oracle.items()} == {k: len(v) for k, v in shuffled.items()}
    # permutation stays within teams: the team-2 edge still holds team-2 players
    assert shuffled["east"] == {4, 5, 6}
    seeds_differ = [make_router("shuffled-hypergraph", seed=s).edges(CTX)["north"]
                    for s in range(10)]
    assert len({frozenset(e) for e in seeds_differ}) > 1


# ---------------------------------------------------------------- self-organized


def test_self_organized_lifecycle():
    r = make_router("self-organized", max_memberships=2, scope="team")
    ok, msg, _ = r.apply(1, ChannelOp("create", "#Hydra Strike!", "kill the hydra"), CTX, 1)
    assert ok and "hydra-strike" in msg
    assert r.channels(1, CTX) == ["hydra-strike"]
    assert not r.apply(2, ChannelOp("create", "hydra-strike"), CTX, 1)[0]  # exists
    assert r.apply(2, ChannelOp("join", "hydra-strike"), CTX, 2)[0]
    assert r.route(1, "hydra-strike", "go", CTX, {}) == [2]
    assert r.route(3, "hydra-strike", "sneaky", CTX, {}) == []  # non-member can't post

    ok, _, others = r.apply(1, ChannelOp("invite", "hydra-strike", player=3), CTX, 3)
    assert ok and "invites you" in others[3]
    assert not r.apply(1, ChannelOp("invite", "hydra-strike", player=4), CTX, 3)[0]  # other team

    r.apply(1, ChannelOp("create", "golem"), CTX, 4)
    ok, msg, _ = r.apply(1, ChannelOp("create", "third"), CTX, 4)
    assert not ok and "leave one first" in msg  # membership cap

    r.apply(1, ChannelOp("leave", "golem"), CTX, 5)
    assert all(c["name"] != "golem" for c in r.directory(1, CTX))  # empty channels vanish
    assert r.directory(4, CTX) == []  # other team can't see team 1's channels
    assert r.stats()["channels_created"] == 2


def test_directory_orders_by_activity():
    r = make_router("self-organized")
    r.apply(1, ChannelOp("create", "old"), CTX, 1)
    r.apply(2, ChannelOp("create", "new"), CTX, 5)
    assert [c["name"] for c in r.directory(3, CTX)] == ["new", "old"]
    r.touch(1, "old", CTX, 9)
    assert [c["name"] for c in r.directory(3, CTX)][0] == "old"


# ---------------------------------------------------------------- loop integration


class Scripted(GreedyIntentAgent):
    def __init__(self, pid, cfg, plan):
        super().__init__(pid, cfg)
        self.plan = plan  # tick -> Decision
        self.reports = []

    def decide(self, obs, report):
        self.reports.append((obs.tick, report))
        return self.plan.get(obs.tick, Decision([Intent("wait", ticks=3)]))


def test_channel_ops_then_messages_reach_only_members():
    cfg = BombermanConfig(num_players=4)
    plans = {
        1: {0: Decision([Intent("wait", ticks=3)], [OutMessage("squad", "hi squad")],
                        channel_ops=[ChannelOp("create", "squad", "test")])},
        2: {0: Decision([Intent("wait", ticks=3)],
                        channel_ops=[ChannelOp("join", "squad")])},
    }
    agents = [Scripted(p, cfg, plans.get(p, {})) for p in range(1, 5)]
    result = run_game(BombermanGame(cfg, seed=1), agents, comms=make_router("self-organized"),
                      max_ticks=10, wake_on_message=False, heartbeat=3)
    msgs = result.log.of_kind("message")
    assert msgs and msgs[0].data["to"] == [2]  # P2 joined in the same tick, before P1 sent
    assert result.log.of_kind("channel")
    later = [r for t, r in agents[1].reports if t > 0]
    assert any(m.text == "hi squad" for r in later for m in r.messages)
    assert all(not r.messages for t, r in agents[2].reports)
    assert result.comms["channels_created"] == 1


def test_messages_never_wake_agents_when_disabled():
    cfg = BombermanConfig(num_players=2)
    talker = {0: Decision([Intent("wait", ticks=50)], [OutMessage("all", "wake up")])}
    agents = [Scripted(1, cfg, talker), Scripted(2, cfg, {0: Decision([Intent("wait",
                                                                             ticks=50)])})]
    run_game(BombermanGame(cfg, seed=1), agents, comms=make_router("broadcast"),
             max_ticks=20, wake_on_message=False)
    assert [r.reason for _, r in agents[1].reports] == ["start"]


def test_inbox_cap_drops_oldest_with_notice():
    cfg = BombermanConfig(num_players=4)
    two = [OutMessage("all", "a"), OutMessage("all", "b")]
    loud = {0: Decision([Intent("wait", ticks=2)], two)}
    agents = [Scripted(p, cfg, loud if p < 4 else {}) for p in range(1, 5)]
    result = run_game(BombermanGame(cfg, seed=1), agents, comms=make_router("broadcast"),
                      max_ticks=6, inbox_cap=2, wake_on_message=False)
    later = [r for t, r in agents[3].reports if t > 0][0]
    assert len(later.messages) == 2
    assert any("dropped" in n for n in later.notices)
    assert result.comms["dropped"] >= 4


# ---------------------------------------------------------------- agent side


class FakeProvider:
    model = "fake"

    def __init__(self, calls):
        self.calls = calls
        self.requests = []

    def complete(self, instructions, items, tools, previous_response_id=None, **kw):
        self.requests.append({"items": items, "tools": tools, "previous": previous_response_id})
        return Completion(self.calls, "", f"r{len(self.requests)}", Usage(calls=1))


def give(**args):
    base = {"orders": [{"action": "wait", "row": 0, "col": 0, "ticks": 2, "why": ""}]}
    return [ToolCall("c1", "give_orders", base | args)]


def test_agent_gets_channel_tools_and_directory():
    provider = FakeProvider(give(channel_ops=[{"op": "create", "channel": "north",
                                               "purpose": "stones up north", "player": 0}],
                                 messages=[{"channel": "north", "text": "x" * 500}]))
    agent = LLMIntentAgent(1, BombermanConfig(), provider)
    report = Report("start", channels=[], comms_info="Make channels.", can_manage_channels=True,
                    directory=[{"name": "south", "purpose": "bottom half", "members": [2, 3],
                                "member": False}])
    decision = agent.decide(BombermanGame(seed=1).observe(1), report)
    assert decision.channel_ops[0].op == "create"
    assert len(decision.messages[0].text) == 200
    props = provider.requests[0]["tools"][0]["parameters"]["properties"]
    assert "channel_ops" in props
    assert "enum" not in props["messages"]["items"]["properties"]["channel"]
    content = provider.requests[0]["items"][-1]["content"]
    assert "#south: 2 member(s) [P2 P3] - bottom half" in content


def test_window_memory_is_stateless_with_recent_turns():
    provider = FakeProvider(give())
    agent = LLMIntentAgent(1, BombermanConfig(), provider, memory="window", window=2)
    obs = BombermanGame(seed=1).observe(1)
    for _ in range(4):
        agent.decide(obs, Report("all orders complete"))
    last = provider.requests[-1]
    assert last["previous"] is None
    content = last["items"][-1]["content"]
    assert content.startswith("YOUR RECENT TURNS")
    assert content.count("ordered wait(2)") == 2  # window of 2


# ---------------------------------------------------------------- graph baselines


def test_dm_whispers_reach_exactly_one_player():
    dm = make_router("dm")
    assert dm.route(1, "@P3", "x", CTX, {}) == [3]
    assert dm.route(1, "p3", "x", CTX, {}) == [3]
    assert dm.route(1, "@P1", "x", CTX, {}) == []  # not to yourself
    assert dm.route(1, "@P99", "x", CTX, {}) == []
    assert make_router("dm", scope="team").route(1, "@P4", "x", CTX, {}) == []  # other team


def test_chatbox_has_global_local_whisper_and_groups():
    cb = make_router("chatbox", local_radius=1)
    assert cb.route(3, "global", "x", CTX, {}) == [1, 2, 4, 5, 6]
    assert cb.route(3, "local", "x", CTX, {}) == [2, 4]  # distance |a-b| <= 1
    assert cb.route(3, "@P6", "x", CTX, {}) == [6]
    cb.apply(3, ChannelOp("create", "raid"), CTX, 1)
    cb.apply(5, ChannelOp("join", "raid"), CTX, 1)
    assert cb.route(3, "raid", "x", CTX, {}) == [5]
    assert cb.channels(3, CTX) == ["global", "local", "raid"]
    assert cb.accepts(3, "@P2", CTX) and not cb.accepts(3, "nonsense", CTX)


def test_loop_delivers_whispers_through_free_channels():
    cfg = BombermanConfig(num_players=3)
    plan = {0: Decision([Intent("wait", ticks=3)], [OutMessage("@P3", "psst")])}
    agents = [Scripted(p, cfg, plan if p == 1 else {}) for p in range(1, 4)]
    run_game(BombermanGame(cfg, seed=1), agents, comms=make_router("dm"), max_ticks=6,
             wake_on_message=False, heartbeat=2)
    assert any(m.text == "psst" for _, r in agents[2].reports for m in r.messages)
    assert all(not r.messages for _, r in agents[1].reports)
