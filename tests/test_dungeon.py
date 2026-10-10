import pytest

from mudllm.agents.dungeon_scripted import IndependentAgent, OracleAgent
from mudllm.comms import make_router
from mudllm.control import Intent
from mudllm.control.dungeon import DungeonController
from mudllm.games.dungeon import DungeonConfig, DungeonGame, ring_monsters
from mudllm.loop import run_game


def game(**kw) -> DungeonGame:
    g = DungeonGame(DungeonConfig(**kw), seed=0)
    for p in g.players.values():
        p.mana = g.config.mana_max
    return g


def kinds(events):
    return [e.kind for e in events]


# ---------------------------------------------------------------- layout


def test_ring_monsters_overlap_by_one_room():
    monsters = dict(ring_monsters(8))
    assert monsters == {"Hydra": (0, 1, 2), "Golem": (2, 3, 4), "Wyrm": (4, 5, 6),
                        "Lich": (6, 7, 0)}


def test_players_spawn_round_robin_with_random_mana():
    g = DungeonGame(DungeonConfig(), seed=3)
    assert [g.players[p].room for p in (1, 8, 9, 16)] == [0, 7, 0, 7]
    assert len({p.mana for p in g.players.values()}) > 1
    assert DungeonGame(DungeonConfig(), seed=3).players[5].mana == g.players[5].mana


def test_moves_take_the_short_way_around_the_ring():
    g = game(num_players=1)
    g.step({1: ("move", 7)})
    assert g.players[1].room == 7


# ---------------------------------------------------------------- combat


def test_fire_damage_grows_with_distinct_stacks_and_consumes_them():
    g = game(num_players=3, num_rooms=8)  # P1 room 0, P2 room 1, P3 room 2: all on the Hydra
    g.step({1: ("ice", "hydra"), 2: ("ice", "hydra")})
    events = g.step({3: ("fire", "hydra")})
    fire = next(e for e in events if e.kind == "fire")
    c = g.config
    assert fire.data["stacks"] == 2
    assert fire.data["damage"] == c.fire_base * c.fire_multiplier ** 2
    assert g.monsters["hydra"].stacks == {}


def test_ice_and_fire_in_the_same_tick_count():
    g = game(num_players=3)
    events = g.step({1: ("ice", "hydra"), 2: ("ice", "hydra"), 3: ("fire", "hydra")})
    assert next(e for e in events if e.kind == "fire").data["stacks"] == 2


def test_one_stack_per_player_and_stacks_expire():
    g = game(num_players=2)
    g.step({1: ("ice", "hydra")})
    for p in g.players.values():
        p.mana = g.config.mana_max
    g.step({1: ("ice", "hydra")})
    assert len(g.monsters["hydra"].stacks) == 1
    for _ in range(g.config.ice_duration):
        g.step({})
    events = g.step({2: ("fire", "hydra")})
    assert next(e for e in events if e.kind == "fire").data["stacks"] == 0


def test_stack_cap():
    g = game(num_players=16, stack_cap=3)
    on_hydra = [p.id for p in g.players.values() if p.room in (0, 1, 2)]
    shooter, icers = on_hydra[0], on_hydra[1:]
    g.step({pid: ("ice", "hydra") for pid in icers})
    events = g.step({shooter: ("fire", "hydra")})
    fire = next(e for e in events if e.kind == "fire").data
    c = g.config
    assert fire["stacks"] == len(icers) > c.stack_cap
    assert fire["damage"] == c.fire_base * c.fire_multiplier ** c.stack_cap


def test_mana_and_room_checks():
    g = game(num_players=1)
    g.players[1].mana = 3
    events = g.step({1: ("ice", "hydra")})
    assert kinds(events) == ["action_failed"] and "mana" in events[0].data["reason"]
    events = g.step({1: ("fire", "golem")})  # golem is rooms 2-4
    assert "not in room" in events[0].data["reason"]


def test_regen_and_kill():
    g = game(num_players=1, monster_hp=30, regen=5)
    g.monsters["hydra"].hp = 10
    g.step({})
    assert g.monsters["hydra"].hp == 15
    g.monsters["hydra"].hp = 1
    events = g.step({1: ("attack", "hydra")})
    assert "monster_killed" in kinds(events) and not g.monsters["hydra"].alive
    g.step({})
    assert g.monsters["hydra"].hp == 0  # the dead don't regenerate


# ---------------------------------------------------------------- visibility & comms context


def test_observation_shows_only_local_stacks():
    g = game(num_players=2)  # P1 room 0, P2 room 1
    g.step({1: ("ice", "hydra")})
    mine = g.observe(1).monsters_here[0]
    theirs = g.observe(2).monsters_here[0]
    assert mine["stacks_here"] and not theirs["stacks_here"]
    assert g.observe(2).monsters_here[0]["hp"] == mine["hp"]  # shared HP is visible


def test_hyperedges_follow_monster_rooms():
    g = game(num_players=8)
    edges = g.hyperedges()
    assert edges["hydra"] == {1, 2, 3} and edges["lich"] == {7, 8, 1}
    assert set(make_router("hypergraph").channels(1, g)) == {"hydra", "lich"}


# ---------------------------------------------------------------- controller


def drive(g, c, ticks):
    for _ in range(ticks):
        events = g.step({c.player_id: c.act(g.observe(c.player_id))})
        c.observe(events)


def test_scheduled_ice_lands_on_exact_tick():
    g = game(num_players=1)
    c = DungeonController(g, 1)
    c.set_intents([Intent("ice", params={"monster": "hydra", "at_tick": 4})], 0)
    drive(g, c, 6)
    outcome = c.drain_outcomes()[0]
    assert outcome.status == "done" and "at t4" in outcome.detail


def test_missed_schedule_fails_instead_of_firing_late():
    g = game(num_players=1)
    for _ in range(5):
        g.step({})
    c = DungeonController(g, 1)
    c.set_intents([Intent("fire", params={"monster": "hydra", "at_tick": 3})], g.tick)
    drive(g, c, 1)
    outcome = c.drain_outcomes()[0]
    assert outcome.status == "failed" and "missed" in outcome.detail


def test_move_then_attack():
    g = game(num_players=1)
    c = DungeonController(g, 1)
    c.set_intents([Intent("move", params={"room": 3}),
                   Intent("attack", params={"monster": "golem"}, ticks=2)], 0)
    drive(g, c, 8)
    assert [o.status for o in c.drain_outcomes()] == ["done", "done"]
    assert g.players[1].room == 3 and g.players[1].damage == 2


def test_wrong_room_fails():
    g = game(num_players=1)
    c = DungeonController(g, 1)
    c.set_intents([Intent("fire", params={"monster": "wyrm"})], 0)
    drive(g, c, 1)
    assert c.drain_outcomes()[0].status == "failed"


# ---------------------------------------------------------------- baselines


@pytest.mark.parametrize("seed", [1, 2])
def test_oracle_coordination_beats_independent_play(seed):
    cfg = DungeonConfig()
    g1 = DungeonGame(cfg, seed=seed)
    indep = run_game(g1, [IndependentAgent(p, cfg) for p in g1.players], max_ticks=300)
    g2 = DungeonGame(cfg, seed=seed)
    oracle = run_game(g2, [OracleAgent(p, g2) for p in g2.players], max_ticks=300)
    assert oracle.cleared
    assert not indep.cleared or oracle.ticks * 2 < indep.ticks
    fires = oracle.log.of_kind("fire")
    assert min(f.data["stacks"] for f in fires) >= 3


def test_room_capacity_blocks_moves():
    g = game(num_players=4, num_rooms=4, room_capacity=1)  # one player per room already
    events = g.step({1: ("move", 1)})
    assert kinds(events) == ["move_blocked"] and g.players[1].room == 0
    c = DungeonController(g, 1)
    c.set_intents([Intent("move", params={"room": 1})], g.tick)
    drive(g, c, 1)
    assert c.drain_outcomes()[0].status == "failed"
