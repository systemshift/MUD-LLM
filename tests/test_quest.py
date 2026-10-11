import pytest

from mudllm.agents.quest_scripted import LocalAgent, OracleAgent, OraclePlanner
from mudllm.comms import make_router
from mudllm.control import Intent
from mudllm.control.quest import QuestController
from mudllm.games.quest import QuestConfig, QuestGame
from mudllm.games.quest.game import Quest
from mudllm.loop import run_game


def world(n=10, **kw) -> QuestGame:
    g = QuestGame(QuestConfig(num_players=n, quest_rate=0.0, initial_quests=0, **kw), seed=4)
    return g


def add(g: QuestGame, kind: str, zone: int = 0, **kw) -> Quest:
    q = Quest(len(g.quests) + 1, kind, zone, 3, g.tick, g.tick + 100, **kw)
    if kind == "boss":
        q.hp = q.max_hp = g.config.boss_hp
    g.quests[q.id] = q
    g.points_spawned += q.points
    return q


def place(g: QuestGame, pid: int, zone: int, cls: str | None = None):
    g.players[pid].zone = zone
    if cls:
        g.players[pid].cls = cls


def kinds(events):
    return [e.kind for e in events if e.kind != "tick_state"]


# ---------------------------------------------------------------- world


def test_world_is_connected_and_deterministic():
    g = QuestGame(QuestConfig(num_players=32), seed=2)
    assert all(d >= 0 for row in g.dist for d in row)
    assert QuestGame(QuestConfig(num_players=32), seed=2).edges == g.edges
    assert QuestGame(QuestConfig(num_players=32), seed=3).edges != g.edges
    assert len({p.cls for p in g.players.values()}) == 5


def test_quests_spawn_at_configured_rate_and_expire():
    g = QuestGame(QuestConfig(num_players=20, quest_rate=0.05, initial_quests=0,
                              deadline=(5, 5)), seed=1)
    for _ in range(10):
        g.step({})
    assert len(g.quests) == 10  # 20 players * 0.05 per tick * 10 ticks
    assert any(q.status == "expired" for q in g.quests.values())
    assert g.score() == 0.0


# ---------------------------------------------------------------- quest rules


def test_ritual_needs_the_class_mix_for_hold_ticks():
    g = world()
    q = add(g, "ritual", need={"frost": 1, "healer": 1})
    place(g, 1, 0, "frost")
    place(g, 2, 0, "healer")
    place(g, 3, 0, "fire")
    g.step({1: ("perform", q.id), 3: ("perform", q.id)})
    assert q.progress == 0  # healer missing
    for _ in range(g.config.hold):
        events = g.step({1: ("perform", q.id), 2: ("perform", q.id)})
    assert "quest_done" in kinds(events) and q.status == "done"
    assert g.players[1].points == pytest.approx(q.points / 2)


def test_vault_needs_key_carrier_and_locksmith():
    g = world()
    q = add(g, "vault", zone=0, key_zone=5)
    place(g, 1, 5)
    place(g, 2, 0, "locksmith")
    assert "pick" in kinds(g.step({1: ("pick", q.id)}))
    for _ in range(3):
        g.step({2: ("perform", q.id)})
    assert q.status == "active"  # key not at the vault yet
    place(g, 1, 0)
    for _ in range(g.config.hold):
        g.step({2: ("perform", q.id)})
    assert q.status == "done" and g.players[1].inventory == []


def test_gates_must_be_held_at_once():
    g = world()
    q = add(g, "gates", zone=0, gates=[0, 3, 6])
    for pid, z in [(1, 0), (2, 3), (3, 6)]:
        place(g, pid, z)
    g.step({1: ("perform", q.id), 2: ("perform", q.id)})
    assert q.progress == 0
    for _ in range(g.config.hold):
        g.step({1: ("perform", q.id), 2: ("perform", q.id), 3: ("perform", q.id)})
    assert q.status == "done"


def test_boss_chill_then_ignite_same_tick_and_cooldowns():
    g = world()
    q = add(g, "boss", zone=0)
    for pid, cls in [(1, "frost"), (2, "frost"), (3, "fire")]:
        place(g, pid, 0, cls)
    # fire has the lower id than nothing here, but ignites still resolve after chills
    events = g.step({3: ("ignite", q.id), 1: ("chill", q.id), 2: ("chill", q.id)})
    ignite = next(e for e in events if e.kind == "ignite").data
    assert ignite["stacks"] == 2 and ignite["damage"] == g.config.fire_base * 9
    events = g.step({1: ("chill", q.id)})
    assert kinds(events) == ["action_failed"]  # cooldown


def test_boss_wounds_and_healer():
    g = world(wound_limit=3)
    q = add(g, "boss", zone=0)
    place(g, 1, 0, "fire")
    place(g, 2, 0, "healer")
    g.step({})
    g.step({})
    assert g.players[1].wounds == 2
    g.step({2: ("heal",)})
    assert g.players[1].wounds == 1  # healed to 0, then wounded again this tick
    events = []
    for _ in range(3):
        events += g.step({})
    assert "downed" in kinds(events)
    assert q.status == "active"


def test_observation_is_local():
    g = world(n=10)
    far = max(range(g.num_zones), key=lambda z: g.dist[0][z])
    add(g, "ritual", zone=far, need={"fire": 1})
    place(g, 1, 0, "fire")
    assert g.observe(1).visible_quests == []
    place(g, 1, far)
    assert len(g.observe(1).visible_quests) == 1


# ---------------------------------------------------------------- controller


def drive(g, c, ticks):
    for _ in range(ticks):
        events = g.step({c.player_id: c.act(g.observe(c.player_id))})
        c.observe(events)
        if c.idle:
            break


def test_controller_goto_pick_and_deliver():
    g = world()
    q = add(g, "vault", zone=0, key_zone=7)
    place(g, 2, 0, "locksmith")
    c = QuestController(g, 1)
    c.set_intents([Intent("goto", params={"zone": 7}), Intent("pick", params={"quest": q.id}),
                   Intent("goto", params={"zone": 0})], 0)
    drive(g, c, 40)
    assert [o.status for o in c.drain_outcomes()] == ["done", "done", "done"]
    assert g.players[1].zone == 0 and q.id in g.players[1].inventory


def test_controller_scheduled_chill_and_wrong_zone():
    g = world()
    q = add(g, "boss", zone=0)
    place(g, 1, 0, "frost")
    c = QuestController(g, 1)
    c.set_intents([Intent("chill", params={"quest": q.id, "at_tick": 3})], 0)
    drive(g, c, 5)
    out = c.drain_outcomes()[0]
    assert out.status == "done" and "t3" in out.detail
    place(g, 1, 5)
    c.set_intents([Intent("perform", params={"quest": q.id})], g.tick)
    drive(g, c, 1)
    assert c.drain_outcomes()[0].status == "failed"


# ---------------------------------------------------------------- baselines & comms


@pytest.mark.parametrize("seed", [1, 2])
def test_oracle_beats_local_play(seed):
    cfg = QuestConfig(num_players=16)
    g = QuestGame(cfg, seed=seed)
    local = run_game(g, [LocalAgent(p, g) for p in g.players], max_ticks=150, heartbeat=10)
    g2 = QuestGame(cfg, seed=seed)
    planner = OraclePlanner(g2)
    oracle = run_game(g2, [OracleAgent(p, planner) for p in g2.players], max_ticks=150,
                      heartbeat=5)
    assert oracle.game["score"] > local.game["score"] + 0.3


def test_oracle_hyperedges_follow_quests():
    g = world()
    q = add(g, "ritual", zone=0, need={"healer": 1})
    place(g, 1, 0, "healer")
    place(g, 2, 0, "fire")
    edges = g.hyperedges()
    assert 1 in edges[f"q{q.id}-ritual"] and 2 not in edges[f"q{q.id}-ritual"]
    assert make_router("hypergraph").channels(1, g) == [f"q{q.id}-ritual"]
