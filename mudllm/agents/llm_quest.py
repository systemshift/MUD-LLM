"""LLM quest-world agent: finds and completes quests with teammates it may never see."""

from ..control import Intent
from ..games.quest import QuestConfig, QuestGame, QuestObservation
from ..games.quest.game import QUEST_POINTS
from .base import Report
from .llm_orders import MAX_ORDERS, LLMOrderAgent

CLASS_INFO = {
    "frost": "chill a boss (one stack per frost player, lasts a few ticks); boost fire",
    "fire": "ignite a boss: damage multiplies x3 per active frost stack, then stacks clear",
    "healer": "heal: clears wounds of everyone in your zone (bosses wound players)",
    "scout": "you see quests and keys 2 zones away instead of 1",
    "locksmith": "required to unlock vaults",
}


def world_map(game: QuestGame) -> str:
    lines = []
    for r, region in enumerate(game.region_names):
        zones = [z for z in range(game.num_zones) if game.zone_region[z] == r]
        lines.append(f"{region}: " + "; ".join(
            f"{z} {game.zone_names[z]} (exits {','.join(map(str, game.adj[z]))})" for z in zones))
    return "\n".join(lines)


def system_prompt(c: QuestConfig, game: QuestGame, cls: str) -> str:
    return f"""You are one of {c.num_players} cooperative adventurers in a quest world. The team scores points by completing quests before they expire; score = points earned / points of all quests that appeared.

YOUR CLASS: {cls}. {CLASS_INFO[cls]}.
Classes on the team: frost, fire, healer, scout, locksmith.

QUESTS (each has a zone, points, and a deadline tick; new ones keep appearing):
- ritual ({QUEST_POINTS["ritual"]} pts): the listed class mix must all `perform` in the quest zone at the same time for {c.hold} consecutive ticks.
- vault ({QUEST_POINTS["vault"]} pts): its key lies in another zone. Someone must `pick` it up and carry it to the vault zone while a locksmith `perform`s there for {c.hold} ticks.
- gates ({QUEST_POINTS["gates"]} pts): three gate zones must each have someone `perform`ing at the same time for {c.hold} consecutive ticks.
- boss ({QUEST_POINTS["boss"]} pts, {c.boss_hp} HP, regenerates {c.boss_regen}/tick): frost players `chill` (one stack each, {c.chill_duration} ticks, cooldown {c.chill_cooldown}); a fire player `ignite`s for {c.fire_base} x 3^stacks (cooldown {c.ignite_cooldown}); anyone can `attack` for {c.attack_damage}. Bosses wound everyone in their zone each tick; at {c.wound_limit} wounds you are downed for {c.downed_ticks} ticks unless a healer `heal`s.
Within a tick, chills land before ignites, so chill and ignite on the same tick to combine them.

WHAT YOU SEE: your zone and zones within {c.view_hops} hop ({c.scout_view_hops} for scouts): quests and keys there, and players in your own zone. You do NOT see quests elsewhere or where other players are. Most quests need players you can't see, so useful information has to be shared if you can communicate.

ORDERS (give_orders, up to {MAX_ORDERS}, run in order; if one fails the rest are cancelled):
- goto(zone) walks the shortest path, 1 zone per tick
- perform(quest, ticks) | pick(quest) | drop(quest) | chill(quest, at_tick) | ignite(quest, at_tick) | attack(quest, ticks) | heal(ticks) | wait(ticks)
- at_tick schedules chill/ignite for an exact tick (0 = as soon as off cooldown); a scheduled action that can't happen then fails.
You are woken when your orders finish or fail, and every few ticks. Communication options, if any, are described each turn.

MAP (zone id, name, exits; regions in order):
{world_map(game)}"""


ORDER_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["goto", "perform", "pick", "drop", "chill",
                                              "ignite", "attack", "heal", "wait"]},
        "zone": {"type": "integer", "description": "goto target zone id, else 0"},
        "quest": {"type": "integer", "description": "quest id, else 0"},
        "at_tick": {"type": "integer", "description": "chill/ignite exact tick, 0 = asap"},
        "ticks": {"type": "integer", "description": "duration for perform/attack/heal/wait"},
        "why": {"type": "string", "description": "a few words"},
    },
    "required": ["action", "zone", "quest", "at_tick", "ticks", "why"],
    "additionalProperties": False,
}


def describe_quest(q: dict) -> str:
    base = f"quest {q['id']} {q['kind']} ({q['points']} pts, due t{q['deadline']})"
    if q["kind"] == "ritual":
        need = ", ".join(f"{n} {cls}" for cls, n in q["need"].items())
        return f"{base} at zone {q['zone']} {q['zone_name']}: needs {need}; progress {q['progress']}"
    if q["kind"] == "gates":
        gates = ", ".join(f"{z} {name}" for z, name in q["gates"])
        return f"{base}: gates {gates}; progress {q['progress']}"
    if q["kind"] == "vault":
        key = (f"key at zone {q['key_zone']} {q['key_zone_name']}" if q["key_zone"] is not None
               else f"key carried by P{q['key_holder']}" if q["key_holder"] else "key lost")
        return f"{base} vault at zone {q['zone']} {q['zone_name']}; {key}"
    return (f"{base} boss at zone {q['zone']} {q['zone_name']}: {q['hp']}/{q['max_hp']} HP, "
            f"{q['stacks']} frost stack(s)")


class LLMQuestAgent(LLMOrderAgent):
    kind = "llm-quest"

    def __init__(self, player_id: int, game: QuestGame, provider, memory: bool | str = True,
                 think_ticks: int = 0, window: int = 6):
        super().__init__(player_id, provider, memory, window)
        self.game = game
        self._instructions = system_prompt(game.config, game, game.players[player_id].cls)
        self._visible: set[int] = set()

    def instructions(self) -> str:
        return self._instructions

    def order_schema(self) -> dict:
        return ORDER_SCHEMA

    def to_intent(self, order: dict, call_id: str) -> Intent | None:
        a = order.get("action")
        quest = int(order.get("quest", 0) or 0)
        ticks = max(1, int(order.get("ticks", 0) or 0))
        if a == "goto":
            return Intent("goto", params={"zone": int(order.get("zone", 0))}, ref=call_id)
        if a in ("perform", "attack"):
            return Intent(a, params={"quest": quest}, ticks=ticks, ref=call_id)
        if a in ("pick", "drop"):
            return Intent(a, params={"quest": quest}, ref=call_id)
        if a in ("chill", "ignite"):
            return Intent(a, params={"quest": quest, "at_tick": int(order.get("at_tick", 0) or 0)},
                          ref=call_id)
        if a in ("heal", "wait"):
            return Intent(a, ticks=ticks, ref=call_id)
        return None

    def describe(self, obs: QuestObservation) -> str:
        self._visible = {q["id"] for q in obs.visible_quests}
        lines = [f"Tick {obs.tick}. You are P{obs.player_id} ({obs.cls}) at zone {obs.zone} "
                 f"{obs.zone_name} in {obs.region}. Exits: "
                 + ", ".join(f"{z} {n}" for z, n in obs.exits) + "."]
        others = ", ".join(f"P{p} {cls}" for p, cls in obs.players_here) or "nobody"
        lines.append(f"Here with you: {others}.")
        if obs.visible_quests:
            lines.append("Quests you can see:")
            lines += [f"- {describe_quest(q)} [{q['distance']} away]" for q in obs.visible_quests]
        else:
            lines.append("You see no quests nearby.")
        for k in obs.visible_keys:
            lines.append(f"Key for vault quest {k['quest']} lies at zone {k['zone']} "
                         f"{k['zone_name']} (vault at zone {k['vault_zone']} {k['vault_zone_name']}).")
        for item in obs.inventory:
            lines.append(f"You carry the key for quest {item['quest']}: vault at zone "
                         f"{item['vault_zone']} {item['vault_zone_name']}, due t{item['deadline']}.")
        s = obs.status
        lines.append(f"Wounds {s['wounds']}; chill ready t{s['chill_ready']}; "
                     f"ignite ready t{s['ignite_ready']}.")
        lines.append(f"Team: score {obs.team['score']:.0%}, {obs.team['done']} quests done, "
                     f"{obs.team['expired']} expired.")
        return "\n".join(lines)

    def summarize(self, report: Report) -> str:
        """Only what this player could have seen: its own results and quests it knew of."""
        out = []
        for e in report.events:
            d = e.data
            if e.kind == "quest_done" and (self.player_id in d["by"] or d["quest"] in self._visible):
                out.append(f"t{e.tick} quest {d['quest']} ({d['kind']}) completed")
            elif e.kind == "quest_expired" and d["quest"] in self._visible:
                out.append(f"t{e.tick} quest {d['quest']} expired")
            elif e.kind == "action_failed" and d.get("player") == self.player_id:
                out.append(f"t{e.tick} your {d['action']} failed: {d['reason']}")
            elif e.kind == "ignite" and d.get("player") == self.player_id:
                out.append(f"t{e.tick} your ignite: {d['stacks']} stacks, {d['damage']} dmg")
            elif e.kind == "downed" and d.get("player") == self.player_id:
                out.append(f"t{e.tick} you were downed until t{d['until']}")
        return "; ".join(out[-10:])
