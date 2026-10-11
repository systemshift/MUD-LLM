"""LLM dungeon agent: coordinates ice/fire combos on shared monsters through orders and messages."""

from ..control import Intent
from ..games.dungeon import DungeonConfig, DungeonObservation
from .base import Report
from .llm_orders import MAX_ORDERS, LLMOrderAgent


def system_prompt(c: DungeonConfig, think_ticks: int) -> str:
    table = ", ".join(f"{k}->{c.fire_base * c.fire_multiplier ** min(k, c.stack_cap)}"
                      for k in range(c.stack_cap + 1))
    monsters = "; ".join(f"{name} in rooms {', '.join(map(str, rooms))}"
                         for name, rooms in c.monster_list())
    timing = (f"The game keeps running while you think: each turn costs about {think_ticks} ticks, "
              f"so schedule actions far enough ahead." if think_ticks else
              "The game pauses while you think.")
    return f"""You are one of {c.num_players} players in a cooperative dungeon. The team wins by killing every monster; faster is better.

MAP: {c.num_rooms} rooms on a ring (room {c.num_rooms - 1} is next to room 0). Moving one room takes 1 tick; a room holds at most {c.room_capacity} players (moving into a full room fails). Monsters: {monsters}.
A monster spans several rooms and has ONE shared HP pool ({c.monster_hp} HP) that regenerates {c.regen} HP every tick, so slow damage never wins and even the biggest fire takes several bursts.

ACTIONS (one per tick; you have {c.mana_max} max mana, +{c.mana_regen} per tick):
- ice (costs {c.ice_cost} mana): puts YOUR ice stack on a monster in your room for {c.ice_duration} ticks. Each player has at most one stack per monster.
- fire (costs {c.fire_cost} mana): damage = {c.fire_base} x {c.fire_multiplier}^k, where k = number of DIFFERENT players with an active ice stack on that monster (any room), capped at {c.stack_cap}. Then all stacks on it are consumed. k->damage: {table}.
- attack (free): {c.attack_damage} damage.
Within one tick, ice lands before fire: if several players ice at tick T and another player fires at tick T, those stacks count.

WHAT YOU CAN SEE: only your own room: its players, the monsters' HP, and ice stacks applied in THIS room. You cannot see stacks applied in other rooms or where other players are. Kills are announced to everyone.
So a big fire needs several players to ice the same monster at the same moment and one player to fire right after, and you can only arrange that by agreeing on it. Fires with few stacks waste mana and consume everyone's stacks.

ORDERS (give_orders, up to {MAX_ORDERS}, run in order; if one fails the rest are cancelled):
- move(room) | ice(monster, at_tick) | fire(monster, at_tick) | attack(monster, ticks) | wait(ticks)
- at_tick schedules ice/fire for an exact game tick (0 = as soon as you have the mana). A scheduled action that can't happen on its tick (wrong room, not enough mana) fails instead of going out late.
You are woken when your orders finish or fail, when your last order starts, and when messages arrive. {timing}
Communication options, if any, are described each turn."""


ORDER_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["move", "ice", "fire", "attack", "wait"]},
        "monster": {"type": "string", "description": "monster name (ice/fire/attack), else empty"},
        "room": {"type": "integer", "description": "target room (move), else 0"},
        "at_tick": {"type": "integer", "description": "exact tick for ice/fire, 0 = asap"},
        "ticks": {"type": "integer", "description": "duration (attack/wait), else 0"},
        "why": {"type": "string", "description": "a few words"},
    },
    "required": ["action", "monster", "room", "at_tick", "ticks", "why"],
    "additionalProperties": False,
}


class LLMDungeonAgent(LLMOrderAgent):
    kind = "llm-dungeon"

    def __init__(self, player_id: int, config: DungeonConfig, provider,
                 memory: bool | str = True, think_ticks: int = 0, window: int = 6):
        super().__init__(player_id, provider, memory, window)
        self.config = config
        self._instructions = system_prompt(config, think_ticks)
        self._room = None

    def instructions(self) -> str:
        return self._instructions

    def order_schema(self) -> dict:
        return ORDER_SCHEMA

    def to_intent(self, order: dict, call_id: str) -> Intent | None:
        action = order.get("action")
        monster = str(order.get("monster", "")).strip().lower()
        if action == "move":
            return Intent("move", params={"room": order.get("room", 0)}, ref=call_id)
        if action in ("ice", "fire"):
            params = {"monster": monster}
            if order.get("at_tick"):
                params["at_tick"] = order["at_tick"]
            return Intent(action, params=params, ref=call_id)
        if action == "attack":
            return Intent("attack", params={"monster": monster},
                          ticks=max(1, order.get("ticks", 1)), ref=call_id)
        if action == "wait":
            return Intent("wait", ticks=max(1, order.get("ticks", 1)), ref=call_id)
        return None

    def describe(self, obs: DungeonObservation) -> str:
        self._room = obs.room
        lines = [f"Tick {obs.tick}. You are P{obs.player_id} in room {obs.room}. "
                 f"Mana {obs.mana}/{obs.mana_max}."]
        for m in obs.monsters_here:
            if not m["alive"]:
                lines.append(f"- {m['name']}: dead")
                continue
            stacks = ", ".join(f"P{p} until t{exp - 1}" for p, exp in m["stacks_here"]) or "none"
            lines.append(f"- {m['name']}: {m['hp']}/{m['max_hp']} HP; ice stacks applied in this "
                         f"room: {stacks}")
        if not obs.monsters_here:
            lines.append("- no monsters in this room")
        lines.append(f"Players here: {', '.join(f'P{p}' for p in obs.players_here) or 'none'}.")
        if obs.monsters_dead:
            lines.append(f"Dead monsters: {', '.join(obs.monsters_dead)}.")
        me = obs.me
        lines.append(f"Your totals: {me['damage']} damage, {me['fires']} fires "
                     f"(best {me['best_fire']}), {me['kills']} kills.")
        return "\n".join(lines)

    def summarize(self, report: Report) -> str:
        """Only what this player could have seen: its own actions, its room, and kills."""
        out = []
        for e in report.events:
            d = e.data
            mine = d.get("player") == self.player_id
            if e.kind == "fire" and (mine or d.get("room") == self._room):
                who = "your" if mine else f"P{d['player']}'s"
                out.append(f"t{e.tick} {who} fire on {d['monster']}: {d['stacks']} stacks, "
                           f"{d['damage']} dmg")
            elif e.kind == "ice" and not mine and d.get("room") == self._room:
                out.append(f"t{e.tick} P{d['player']} iced {d['monster']} here")
            elif e.kind == "monster_killed":
                out.append(f"t{e.tick} {d['monster']} was killed")
            elif e.kind == "action_failed" and mine:
                out.append(f"t{e.tick} your {d['action']} failed: {d['reason']}")
        return "; ".join(out[-12:])
