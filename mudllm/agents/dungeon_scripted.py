"""
Scripted dungeon baselines that bracket what communication can buy.

IndependentAgent  no coordination: in its own room, ices then fires the weakest
                  visible monster whenever it has mana. Stacks from others only
                  help by luck.
OracleAgent       perfect coordination by cheating: reads the true game state,
                  splits players into balanced groups per monster, and runs
                  synchronized cycles (everyone ices at T, the group's firer fires
                  at T+1). An upper-bound reference, not a fair player.
"""

from ..control import Intent
from ..games.dungeon import DungeonConfig, DungeonGame, DungeonObservation
from .base import Decision, Report
from .providers import Usage


class IndependentAgent:
    def __init__(self, player_id: int, config: DungeonConfig):
        self.player_id = player_id
        self.config = config
        self.name = "independent"
        self.usage = Usage()
        self.last_orders: list[str] = []

    def decide(self, obs: DungeonObservation, report: Report) -> list[Intent] | Decision:
        if report.reason.startswith("periodic check-in"):
            return Decision([], replace=False)  # keep running orders on heartbeats
        alive = [m for m in obs.monsters_here if m["alive"]]
        if not alive:  # walk to the nearest room with a living monster
            target = _nearest_room_with_monster(obs)
            self.last_orders = [f"move to room {target}"]
            return [Intent("move", params={"room": target})] if target is not None \
                else [Intent("wait", ticks=5)]
        m = min(alive, key=lambda m: m["hp"])["key"]
        # save up for ice + fire back to back (chipping meanwhile) so our own stack counts
        c = self.config
        wait = max(0, -(-(c.ice_cost + c.fire_cost - obs.mana) // c.mana_regen))
        ice_at = obs.tick + 1 + wait
        self.last_orders = [f"ice {m} at t{ice_at}, fire at t{ice_at + 1}"]
        orders = [Intent("attack", params={"monster": m}, ticks=wait)] if wait else []
        return orders + [Intent("ice", params={"monster": m, "at_tick": ice_at}),
                         Intent("fire", params={"monster": m, "at_tick": ice_at + 1})]


class OracleAgent:
    def __init__(self, player_id: int, game: DungeonGame, period: int | None = None):
        self.player_id = player_id
        self.game = game
        c = game.config
        # firer must afford ice + fire each cycle
        self.period = period or -(-(c.ice_cost + c.fire_cost) // c.mana_regen)
        self.name = "oracle"
        self.usage = Usage()
        self.last_orders: list[str] = []

    def groups(self) -> dict[str, list[int]]:
        """Balanced assignment of players to living monsters in their room."""
        g = self.game
        groups: dict[str, list[int]] = {m.key: [] for m in g.monsters.values() if m.alive}
        for p in sorted(g.players.values(), key=lambda p: p.id):
            options = [m.key for m in g.monsters_in(p.room) if m.alive]
            if options:
                groups[min(options, key=lambda k: (len(groups[k]), k))].append(p.id)
        return groups

    def decide(self, obs: DungeonObservation, report: Report) -> list[Intent] | Decision:
        if report.reason.startswith("periodic check-in"):
            return Decision([], replace=False)  # keep running orders on heartbeats
        groups = self.groups()
        mine = next((k for k, members in groups.items() if self.player_id in members), None)
        if mine is None:
            target = _nearest_room_with_monster(obs)
            self.last_orders = [f"move to room {target}"]
            return [Intent("move", params={"room": target})] if target is not None \
                else [Intent("wait", ticks=5)]
        # next cycle start, leaving a tick to get there
        t = obs.tick + 1
        start = t + (-t % self.period)
        firer = min(groups[mine])
        # chip with free attacks until the cycle starts
        orders = [Intent("attack", params={"monster": mine}, ticks=start - t)] if start > t else []
        orders.append(Intent("ice", params={"monster": mine, "at_tick": start}))
        if self.player_id == firer:
            orders.append(Intent("fire", params={"monster": mine, "at_tick": start + 1}))
        self.last_orders = [f"{'ice+fire' if self.player_id == firer else 'ice'} {mine} "
                            f"at t{start} (group {groups[mine]})"]
        return orders


def _nearest_room_with_monster(obs: DungeonObservation) -> int | None:
    n = len(obs.rooms)
    alive_rooms = [r for r, names in obs.rooms.items()
                   if any(name not in obs.monsters_dead for name in names)]
    if not alive_rooms:
        return None
    return min(alive_rooms, key=lambda r: (min((r - obs.room) % n, (obs.room - r) % n), r))
