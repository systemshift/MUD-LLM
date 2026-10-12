import pytest

from mudllm.agents.quest_scripted import LocalAgent, OracleAgent, OraclePlanner
from mudllm.control import Intent
from mudllm.control.quest import QuestController
from mudllm.games.quest import QuestConfig, QuestGame
from mudllm.games.quest.game import RESOURCES, Quest
from mudllm.loop import run_game


def world(n=10, **kw) -> QuestGame:
    return QuestGame(QuestConfig(num_players=n, mmo=True, quest_rate=0.0, initial_quests=0,
                                 **kw), seed=4)


def zone_with(g, res):
    return next(z for z in range(g.num_zones) if g.zone_resource[z] == res)


def kinds(events):
    return [e.kind for e in events if e.kind != "tick_state"]


@pytest.mark.parametrize("n", [8, 16, 32, 64])
def test_every_resource_exists_at_every_size(n):
    g = QuestGame(QuestConfig(num_players=n, mmo=True), seed=1)
    assert set(g.zone_resource) == set(RESOURCES)


def test_gather_craft_and_give():
    g = world()
    p, q = g.players[1], g.players[2]
    p.zone = zone_with(g, "herb")
    for _ in range(g.config.gather_ticks):
        events = g.step({1: ("gather",)})
    assert "gather" in kinds(events) and p.items["herb"] == 1
    assert kinds(g.step({1: ("craft", "potion")})) == ["action_failed"]  # no crystal yet
    p.items["crystal"] = 1
    g.step({1: ("craft", "potion")})
    assert p.items["potion"] == 1 and p.items["herb"] == 0
    q.zone = (p.zone + 1) % g.num_zones if g.num_zones > 1 else p.zone
    assert kinds(g.step({1: ("give", "potion", 2)})) == ["action_failed"]  # not co-located
    q.zone = p.zone
    g.step({1: ("give", "potion", 2)})
    assert q.items["potion"] == 1 and p.items["potion"] == 0


def test_delivery_completes_when_carrier_performs_there():
    g = world()
    q = Quest(1, "delivery", 3, 5, 0, 100, item="torch")
    g.quests[1] = q
    g.points_spawned += q.points
    g.players[1].zone = 3
    g.step({1: ("perform", 1)})
    assert q.status == "active"
    g.players[1].items["torch"] = 1
    g.step({1: ("perform", 1)})
    assert q.status == "done" and g.players[1].items["torch"] == 0


def test_item_ritual_needs_a_carrier():
    g = world()
    q = Quest(1, "ritual", 0, 3, 0, 100, need={"frost": 1}, item="charm")
    g.quests[1] = q
    g.players[1].zone, g.players[1].cls = 0, "frost"
    for _ in range(g.config.hold + 1):
        g.step({1: ("perform", 1)})
    assert q.status == "active"
    g.players[1].items["charm"] = 1
    for _ in range(g.config.hold):
        g.step({1: ("perform", 1)})
    assert q.status == "done" and g.players[1].items["charm"] == 0


def test_raids_are_fought_like_bosses():
    g = world()
    q = Quest(1, "raid", 0, 12, 0, 100, hp=g.config.raid_hp, max_hp=g.config.raid_hp)
    g.quests[1] = q
    for pid, cls in [(1, "frost"), (2, "frost"), (3, "fire")]:
        g.players[pid].zone, g.players[pid].cls = 0, cls
    events = g.step({1: ("chill", 1), 2: ("chill", 1), 3: ("ignite", 1)})
    assert next(e for e in events if e.kind == "ignite").data["stacks"] == 2
    assert "action_failed" in kinds(g.step({4: ("perform", 1)}))  # raids aren't performed


def test_controller_gathers_crafts_and_gives():
    g = world()
    p = g.players[1]
    p.zone = zone_with(g, "wood")
    p.items["ore"] = 1
    g.players[2].zone = p.zone
    c = QuestController(g, 1)
    c.set_intents([Intent("gather", ticks=g.config.gather_ticks),
                   Intent("craft", params={"item": "torch"}),
                   Intent("give", params={"item": "torch", "player": 2})], 0)
    for _ in range(10):
        events = g.step({1: c.act(g.observe(1))})
        c.observe(events)
        if c.idle:
            break
    assert [o.status for o in c.drain_outcomes()] == ["done", "done", "done"]
    assert g.players[2].items["torch"] == 1


def test_mmo_brackets():
    cfg = QuestConfig(num_players=16, mmo=True)
    g1 = QuestGame(cfg, seed=2)
    local = run_game(g1, [LocalAgent(p, g1) for p in g1.players], max_ticks=150, heartbeat=10)
    g2 = QuestGame(cfg, seed=2)
    planner = OraclePlanner(g2)
    oracle = run_game(g2, [OracleAgent(p, planner) for p in g2.players], max_ticks=150,
                      heartbeat=5)
    assert oracle.game["score"] > local.game["score"] + 0.3
    assert oracle.game["by_kind"].get("delivery", [0, 0])[0] > 0
