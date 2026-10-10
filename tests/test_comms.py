import pytest

from mudllm.agents.base import Decision, OutMessage
from mudllm.agents.greedy import GreedyIntentAgent
from mudllm.comms import HashEmbedder, make_router
from mudllm.comms.embed import cosine
from mudllm.control import Intent
from mudllm.games.bomberman import BombermanConfig, BombermanGame
from mudllm.loop import run_game


class Ctx:
    """Four players on a line at positions 0, 1, 5, 6; teams {1,2} and {3,4}."""

    pos = {1: 0, 2: 1, 3: 5, 4: 6}

    def player_ids(self):
        return [1, 2, 3, 4]

    def team(self, pid):
        return 1 if pid <= 2 else 2

    def distance(self, a, b):
        return abs(self.pos[a] - self.pos[b])

    def hyperedges(self):
        return {"hydra": {1, 2, 3}, "golem": {3, 4}}

    def describe_player(self, pid):
        return {1: "room 1 with hydra", 2: "room 2 with hydra", 3: "room 3 with hydra golem",
                4: "room 4 with golem"}[pid]


CTX = Ctx()


def test_none_and_broadcast():
    assert make_router("none").channels(1, CTX) == []
    assert make_router("none").route(1, "all", "hi", CTX, {}) == []
    assert make_router("broadcast").route(1, "all", "hi", CTX, {}) == [2, 3, 4]


def test_team_and_spatial():
    assert make_router("team").route(1, "team", "x", CTX, {}) == [2]
    assert make_router("spatial", radius=1).route(3, "nearby", "x", CTX, {}) == [4]


def test_hypergraph_channels_follow_membership():
    router = make_router("hypergraph")
    assert router.channels(3, CTX) == ["golem", "hydra"]
    assert router.channels(4, CTX) == ["golem"]
    assert router.route(1, "hydra", "ice now", CTX, {}) == [2, 3]
    assert router.route(4, "hydra", "sneaky", CTX, {}) == []  # not a member


def test_vector_routes_by_relevance():
    router = make_router("vector", threshold=0.2, top_k=2)
    focus = {2: "", 3: "", 4: "golem fire timing"}
    assert router.route(1, "auto", "golem needs fire at tick 40", CTX, focus)[0] in (3, 4)
    assert 4 in router.route(1, "auto", "golem fire", CTX, focus)
    assert router.route(1, "auto", "zzz qqq", CTX, focus) == []


def test_hash_embedder_similarity():
    a, b, c = HashEmbedder().embed(["ice the hydra", "hydra ice now", "golem fire"])
    assert cosine(a, b) > cosine(a, c)


def test_unknown_router():
    with pytest.raises(ValueError):
        make_router("telepathy")


# ---------------------------------------------------------------- loop integration


class Talker(GreedyIntentAgent):
    """Greedy agent that says something on its first turn and records what it hears."""

    def __init__(self, pid, cfg, channel):
        super().__init__(pid, cfg)
        self.channel = channel
        self.heard = []
        self.reports = []

    def decide(self, obs, report):
        self.reports.append(report)
        self.heard += [m.text for m in report.messages]
        intents = super().decide(obs, report)
        msgs = [OutMessage(self.channel, f"hello from P{self.player_id}")] if obs.tick == 0 else []
        return Decision(intents, msgs)


def run_talkers(mode, channel, teams=None, **kw):
    cfg = BombermanConfig(num_players=4, teams=teams)
    agents = [Talker(p, cfg, channel) for p in range(1, 5)]
    result = run_game(BombermanGame(cfg, seed=3), agents, comms=make_router(mode, **kw),
                      max_ticks=40)
    return agents, result


def test_broadcast_delivers_to_everyone_and_logs():
    agents, result = run_talkers("broadcast", "all")
    assert sorted(agents[0].heard) == ["hello from P2", "hello from P3", "hello from P4"]
    assert result.comms["sent"] == 4 and result.comms["deliveries"] == 12
    assert len(result.log.of_kind("message")) == 4
    assert result.players[1]["received"] == 3


def test_team_channel_respects_teams():
    agents, result = run_talkers("team", "team", teams=(1, 1, 2, 2))
    assert agents[0].heard == ["hello from P2"]
    assert agents[2].heard == ["hello from P4"]
    assert result.game["team_scores"].keys() == {1, 2}


def test_no_comms_rejects_messages_with_notice():
    agents, result = run_talkers("none", "all")
    assert result.comms["sent"] == 0
    assert any("message not sent" in n for r in agents[0].reports for n in r.notices)
    assert agents[0].reports[0].comms_info.startswith("There is no communication")


def test_messages_wake_agents():
    class Sleeper(GreedyIntentAgent):
        def __init__(self, *a):
            super().__init__(*a)
            self.reasons = []

        def decide(self, obs, report):
            self.reasons.append(report.reason)
            return [Intent("wait", ticks=100)]

    class Shouter(GreedyIntentAgent):
        def decide(self, obs, report):
            return Decision([Intent("wait", ticks=100)],
                            [OutMessage("all", "wake up")] if obs.tick == 0 else [])

    cfg = BombermanConfig(num_players=2)
    sleeper = Sleeper(2, cfg)
    run_game(BombermanGame(cfg, seed=1), [Shouter(1, cfg), sleeper],
             comms=make_router("broadcast"), max_ticks=30, message_cooldown=5)
    assert "new messages" in sleeper.reasons


def test_decision_replace_false_keeps_running_orders():
    from mudllm.control import BombermanController
    g = BombermanGame(BombermanConfig(), seed=1)
    c = BombermanController(g.config, 1)
    c.set_intents([Intent("goto", target=(1, 3))], 0)
    c.set_intents([Intent("wait", ticks=1)], 1, append=True)
    assert [i.kind for i in c.queue] == ["goto", "wait"]
