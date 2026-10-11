import pytest

from mudllm.agents.base import Decision, OutMessage
from mudllm.agents.bomber_scripted import ExplorerAgent, IronPlanner, OracleAgent
from mudllm.comms import PerTeam, make_router
from mudllm.control import BombermanController, Intent
from mudllm.games.bomberman import BombermanConfig, BombermanGame
from mudllm.games.bomberman.game import Bomb
from mudllm.loop import run_game
from mudllm.replay import build_frames


def blank(n=4, **kw) -> BombermanGame:
    """Scaled game with an empty board (sentinel stone far away keeps it running)."""
    g = BombermanGame(BombermanConfig.scaled(n, stone_probability=0.0, **kw), seed=1)
    g.grid[1][1] = "S"
    g.initial_stones = 1
    return g


def kinds(events):
    return [e.kind for e in events]


# ---------------------------------------------------------------- setup


@pytest.mark.parametrize("n", [16, 64, 128])
def test_scaled_maps_spawn_everyone_on_floor(n):
    cfg = BombermanConfig.scaled(n)
    g = BombermanGame(cfg, seed=2)
    assert cfg.width * cfg.height >= n * 50
    assert len({p.pos for p in g.players.values()}) == n
    assert all(g.walkable(p.pos) for p in g.players.values())
    assert g.initial_iron > 0 and g.treasures_total > 0


def test_versus_teams_start_on_opposite_halves():
    g = BombermanGame(BombermanConfig.scaled(16, versus=True), seed=1)
    mid = g.config.width // 2
    assert all((p.pos[1] < mid) == (g.team(p.id) == 1) for p in g.players.values())


def test_classic_boards_unchanged_by_scaled_features():
    assert BombermanGame(BombermanConfig(), seed=1).treasures_total == 0


# ---------------------------------------------------------------- rules


def test_fog_hides_far_cells_players_and_bombs():
    g = blank(4)
    me = g.players[1]
    far = (me.pos[0], me.pos[1] + g.config.view_radius + 2)
    g.bombs.append(Bomb(far, 2, 3))
    obs = g.observe(1)
    assert obs.grid[far[0]][far[1]] == "?"
    assert all(tuple(b["pos"]) != far for b in obs.bombs)
    assert obs.grid[me.pos[0]][me.pos[1]] == "P"


def test_treasure_revealed_by_blast_then_collected():
    g = blank(1)
    r, c = g.players[1].pos
    stone = (r, c + 2)
    g.grid[stone[0]][stone[1]] = "S"
    g.treasures.add(stone)
    g.players[1].pos = (r, c + 1)
    g.step({1: "bomb"})
    for move in ("left", "down", "pass"):  # escape out of line with the blast
        g.step({1: move})
    assert g.grid[stone[0]][stone[1]] == "T"
    g.players[1].pos = (r, c + 1)
    events = g.step({1: "right"})
    assert "treasure" in kinds(events) and g.players[1].treasures == 1


def test_iron_needs_two_players_in_the_same_tick():
    g = blank(2)
    r, c = g.players[1].pos
    iron = (r, c + 2)
    g.grid[iron[0]][iron[1]] = "I"
    g.bombs = [Bomb((r, c + 1), 1, 1)]
    g.step({})
    assert g.cell(iron) == "I"  # one owner: nothing
    g.bombs = [Bomb((r, c + 1), 1, 1), Bomb((r, c + 3), 1, 1)]
    g.step({})
    assert g.cell(iron) == "I"  # two bombs, same owner: nothing
    g.bombs = [Bomb((r, c + 1), 1, 1), Bomb((r, c + 3), 2, 1)]
    events = g.step({})
    assert "iron_broken" in kinds(events) and g.cell(iron) == " "


def test_hit_player_respawns_and_sits_out():
    g = blank(1)
    p = g.players[1]
    p.pos = (p.spawn[0], p.spawn[1] + 1)
    g.bombs = [Bomb(p.pos, 1, 1)]
    events = g.step({})
    hit = next(e for e in events if e.kind == "player_hit").data
    assert p.pos == p.spawn and hit["until"] == g.tick + g.config.respawn_ticks
    g.step({1: "right"})
    assert p.pos == p.spawn  # still knocked out


def test_scheduled_bomb_lands_on_exact_tick():
    g = blank(1)
    r, c = g.players[1].pos
    ctrl = BombermanController(g.config, 1)
    ctrl.set_intents([Intent("bomb_at", target=(r, c + 1), params={"at_tick": 6})], 0)
    placed = None
    for _ in range(8):
        events = g.step({1: ctrl.act(g.observe(1))})
        ctrl.observe(events)
        placed = placed or next((e.tick for e in events if e.kind == "bomb_placed"), None)
    assert placed == 6


def test_controller_remembers_terrain_under_fog():
    g = blank(1)
    r, c = g.players[1].pos
    ctrl = BombermanController(g.config, 1)
    g.grid[r][c + 3] = "S"
    ctrl.remember(g.observe(1))
    g.players[1].pos = (r, c - 1)
    assert g.observe(1).grid[r][c + 3] in "?S"
    assert ctrl.remember(g.observe(1)).grid[r][c + 3] == "S"


# ---------------------------------------------------------------- brackets & comms


def test_oracle_with_iron_pairs_beats_explorer():
    cfg = BombermanConfig.scaled(16)
    g1 = BombermanGame(cfg, seed=1)
    explorer = run_game(g1, [ExplorerAgent(p, cfg) for p in g1.players], max_ticks=100,
                        heartbeat=10)
    g2 = BombermanGame(cfg, seed=1)
    planner = IronPlanner(g2)
    oracle = run_game(g2, [OracleAgent(p, g2, planner) for p in g2.players], max_ticks=100,
                      heartbeat=10)
    assert oracle.game["iron"] > explorer.game["iron"]
    assert oracle.game["score"] > explorer.game["score"] + 0.15


class Shouter(ExplorerAgent):
    def __init__(self, pid, cfg):
        super().__init__(pid, cfg)
        self.heard = []

    def decide(self, obs, report):
        self.heard += [m.text for m in report.messages]
        intents = super().decide(obs, report)
        if obs.tick == 0:
            team = obs.players[obs.player_id]["team"]
            return Decision(intents, [OutMessage("all", f"team{team}")])
        return intents


def test_per_team_routers_never_leak_across_teams():
    cfg = BombermanConfig.scaled(8, versus=True)
    agents = [Shouter(p, cfg) for p in range(1, 9)]
    comms = PerTeam({1: make_router("broadcast"), 2: make_router("none")})
    result = run_game(BombermanGame(cfg, seed=1), agents, comms=comms, max_ticks=15,
                      wake_on_message=False, heartbeat=5)
    team1 = [a for a in agents if cfg.teams[a.player_id - 1] == 1]
    team2 = [a for a in agents if cfg.teams[a.player_id - 1] == 2]
    assert all(set(a.heard) == {"team1"} for a in team1)
    assert all(not a.heard for a in team2)
    assert result.comms["mode"] == "1:broadcast vs 2:none"


def test_scaled_replay_matches_engine():
    cfg = BombermanConfig.scaled(16)
    g = BombermanGame(cfg, seed=3)
    planner = IronPlanner(g)
    snaps = {}
    result = run_game(g, [OracleAgent(p, g, planner) for p in g.players], max_ticks=80,
                      heartbeat=10,
                      on_tick=lambda game, ev: snaps.__setitem__(game.tick, game.snapshot()))
    assert result.game["iron"] > 0 and result.game["treasures"] > 0
    _, frames = build_frames(result.log.events)
    for frame in frames[1:]:
        snap = snaps[frame["tick"]]
        assert frame["grid"] == snap["grid"], frame["tick"]
        for pid, p in snap["players"].items():
            f = frame["players"][pid]
            assert (f["pos"], f["score"], f["downed"]) == (list(p["pos"]), p["score"], p["downed"])
