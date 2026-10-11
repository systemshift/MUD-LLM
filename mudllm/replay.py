"""
Rebuild per-tick frames from an event log.

Frame k is the state after tick k (frame 0 is the start), plus what happened
during that tick: explosions/fires, decisions, messages. The viewer renders
frames directly, so it never re-implements game rules. Game-specific state
reconstruction lives in a small rules class per game.
"""

from typing import Any

from .games.bomberman import BombermanConfig
from .games.dungeon import DungeonConfig
from .sim import Event


class BombermanFrames:
    def __init__(self, init: dict):
        self.config = BombermanConfig(**init["config"]) if "config" in init else BombermanConfig()
        self.state = {
            "grid": [list(row) for row in init["grid"]],
            "players": {int(pid): {"pos": list(p["pos"]), "score": p["score"], "hits": p["hits"],
                                   **({"team": p["team"], "treasures": p.get("treasures", 0),
                                       "downed_until": 0} if "team" in p else {})}
                        for pid, p in init["players"].items()},
            "bombs": [dict(b, pos=list(b["pos"])) for b in init["bombs"]],
        }

    def new_frame(self) -> dict:
        return {"blasts": [], "hits": [], "notes": [], "irons": []}

    def start_tick(self):
        self.tick = getattr(self, "tick", 0) + 1
        for b in self.state["bombs"]:  # fuses burn once per tick
            b["fuse"] -= 1

    def end_tick(self):
        pass

    def apply(self, e: Event, frame: dict):
        d, s, c = e.data, self.state, self.config
        if e.kind == "move":
            s["players"][d["player"]]["pos"] = list(d["to"])
        elif e.kind == "treasure":
            r, col = d["pos"]
            s["grid"][r][col] = " "
            p = s["players"][d["player"]]
            p["score"] += c.treasure_points
            p["treasures"] = p.get("treasures", 0) + 1
        elif e.kind == "iron_broken":
            r, col = d["pos"]
            s["grid"][r][col] = " "
            for o in d["by"]:
                s["players"][o]["score"] += c.iron_points // len(d["by"])
            frame["irons"].append(d)
        elif e.kind == "bomb_placed":
            # the engine already burned this tick's fuse by the end of the placing tick
            s["bombs"].append({"pos": list(d["pos"]), "owner": d["player"], "fuse": c.bomb_fuse})
        elif e.kind == "explosion":
            s["bombs"] = [b for b in s["bombs"] if b["pos"] != list(d["pos"])]
            revealed = {tuple(t) for t in d.get("treasures", [])}
            for r, col in d["stones"]:
                s["grid"][r][col] = "T" if (r, col) in revealed else " "
            if d["owner"] in s["players"]:
                s["players"][d["owner"]]["score"] += c.stone_points * len(d["stones"])
            frame["blasts"].append({"owner": d["owner"], "cells": d["cells"]})
        elif e.kind == "player_hit":
            p = s["players"][d["player"]]
            p["score"] += c.hit_penalty
            p["hits"] += 1
            if "respawn" in d:
                p["pos"] = list(d["respawn"])
                p["downed_until"] = d["until"]
            frame["hits"].append(d["player"])
        elif e.kind in ("move_blocked", "bomb_failed"):
            frame["notes"].append(f"P{d['player']} {e.kind.replace('_', ' ')}")

    def refresh(self, frame: dict):
        s = self.state
        frame["grid"] = ["".join(row) for row in s["grid"]]
        tick = frame["tick"]
        frame["players"] = {}
        for pid, p in s["players"].items():
            fp = dict(p, pos=list(p["pos"]))
            if "downed_until" in p or "team" in p:
                fp["downed"] = p.get("downed_until", 0) > tick
                fp.pop("downed_until", None)
            frame["players"][pid] = fp
        frame["bombs"] = [dict(b, pos=list(b["pos"])) for b in s["bombs"]]
        frame["stones"] = sum(row.count("S") for row in s["grid"])
        frame["iron"] = sum(row.count("I") for row in s["grid"])


class DungeonFrames:
    def __init__(self, init: dict):
        self.config = DungeonConfig(**init["config"]) if "config" in init else DungeonConfig()
        self.tick = 0
        self.state = {
            "rooms": init["rooms"],
            "monsters": {k: {"name": m["name"], "rooms": m["rooms"], "hp": m["hp"],
                             "max_hp": m["max_hp"], "alive": m["alive"],
                             "stacks": {int(p): list(s) for p, s in m["stacks"].items()}}
                         for k, m in init["monsters"].items()},
            "players": {int(pid): dict(p) for pid, p in init["players"].items()},
        }

    def new_frame(self) -> dict:
        return {"fires": [], "ices": [], "kills": [], "failures": []}

    def start_tick(self):
        self.tick += 1

    def end_tick(self):
        """Mirror the engine's end of tick: stacks expire, monsters and mana regenerate."""
        if self.tick == 0:  # frame 0 is the starting state; no tick has run yet
            return
        c = self.config
        for m in self.state["monsters"].values():
            m["stacks"] = {p: s for p, s in m["stacks"].items() if s[1] > self.tick}
            if m["alive"] and m["hp"] < m["max_hp"]:
                m["hp"] = min(m["max_hp"], m["hp"] + c.regen)
        for p in self.state["players"].values():
            p["mana"] = min(c.mana_max, p["mana"] + c.mana_regen)

    def _hit(self, player: int, monster: str, damage: int):
        self.state["monsters"][monster]["hp"] -= damage
        self.state["players"][player]["damage"] += damage

    def apply(self, e: Event, frame: dict):
        d, s, c = e.data, self.state, self.config
        if e.kind == "move":
            s["players"][d["player"]]["room"] = d["to"]
        elif e.kind == "ice":
            s["players"][d["player"]]["mana"] -= c.ice_cost
            s["monsters"][d["monster"]]["stacks"][d["player"]] = [d["room"], d["expires"]]
            self._hit(d["player"], d["monster"], c.attack_damage)
            frame["ices"].append(d)
        elif e.kind == "attack":
            self._hit(d["player"], d["monster"], d["damage"])
        elif e.kind == "fire":
            s["players"][d["player"]]["mana"] -= c.fire_cost
            s["monsters"][d["monster"]]["stacks"] = {}
            self._hit(d["player"], d["monster"], d["damage"])
            frame["fires"].append(d)
        elif e.kind == "monster_killed":
            m = s["monsters"][d["monster"]]
            m.update(hp=0, alive=False, stacks={})
            frame["kills"].append(d)
        elif e.kind == "action_failed":
            frame["failures"].append(d)

    def refresh(self, frame: dict):
        s = self.state
        frame["rooms"] = s["rooms"]
        frame["monsters"] = {k: dict(m, hp=max(0, m["hp"]),
                                     stacks={p: list(v) for p, v in m["stacks"].items()})
                             for k, m in s["monsters"].items()}
        frame["players"] = {pid: dict(p) for pid, p in s["players"].items()}
        frame["alive"] = sum(m["alive"] for m in s["monsters"].values())


class QuestFrames:
    """Quest world logs carry a compact tick_state each tick, so frames copy it exactly."""

    def __init__(self, init: dict):
        self.world = init["world"]
        self.state = {
            "players": {int(pid): dict(p) for pid, p in init["players"].items()},
            "quests": {int(qid): dict(q) for qid, q in init["quests"].items()},
            "score": init.get("score", 0.0),
        }

    def new_frame(self) -> dict:
        return {"done": [], "expired": [], "spawned": [], "ignites": []}

    def start_tick(self):
        pass

    def end_tick(self):
        pass

    def apply(self, e: Event, frame: dict):
        d, s = e.data, self.state
        if e.kind == "tick_state":
            for pid, (zone, wounds, downed) in d["players"].items():
                p = s["players"][int(pid)]
                p.update(zone=zone, wounds=wounds, downed=bool(downed))
            for qid, (progress, hp, stacks, key_zone, holder) in d["quests"].items():
                q = s["quests"].get(int(qid))
                if q:
                    q.update(progress=progress, stacks=stacks, key_zone=key_zone,
                             key_holder=holder)
                    if q["kind"] == "boss":
                        q["hp"] = hp
            s["score"] = d["score"]
        elif e.kind == "quest_spawned":
            s["quests"][d["id"]] = dict(d)
            frame["spawned"].append(d["id"])
        elif e.kind in ("quest_done", "quest_expired"):
            q = s["quests"].get(d["quest"])
            if q:
                q["status"] = "done" if e.kind == "quest_done" else "expired"
            frame["done" if e.kind == "quest_done" else "expired"].append(d)
            if e.kind == "quest_done":
                for pid in d["by"]:
                    s["players"][pid]["points"] = round(
                        s["players"][pid].get("points", 0) + d["points"] / len(d["by"]), 2)
        elif e.kind == "ignite":
            frame["ignites"].append(d)

    def refresh(self, frame: dict):
        s = self.state
        frame["players"] = {pid: dict(p) for pid, p in s["players"].items()}
        frame["quests"] = {qid: dict(q) for qid, q in s["quests"].items()
                           if q.get("status", "active") == "active"}
        frame["score"] = s["score"]


class Replayer:
    """Incremental: feed events as they arrive (live runs) and read frames."""

    def __init__(self):
        self.frames: list[dict[str, Any]] = []
        self.meta: dict[str, Any] = {}
        self._consumed = 0
        self._rules = None

    def feed(self, events: list[Event]):
        for e in events[self._consumed:]:
            self._apply(e)
        self._consumed = max(self._consumed, len(events))

    def _apply(self, e: Event):
        d = e.data
        if e.kind == "init":
            game = d.get("game", "bomberman")
            rules = {"dungeon": DungeonFrames, "quest": QuestFrames}.get(game, BombermanFrames)
            self._rules = rules(d)
            self.meta.update(seed=d.get("seed"), config=d.get("config"), game=game,
                             world=d.get("world"))
            self.frames = [self._frame(0)]
            return
        if e.kind == "meta":
            self.meta.update(d)
            return
        if self._rules is None:
            return

        while self.frames[-1]["tick"] < e.tick:  # first event of a new tick
            self._rules.end_tick()
            self._rules.refresh(self.frames[-1])
            self._rules.start_tick()
            self.frames.append(self._frame(self.frames[-1]["tick"] + 1))
        frame = self.frames[-1]

        if e.kind == "decision":
            frame["decisions"].append(d)
        elif e.kind == "message":
            frame["messages"].append(d)
        elif e.kind == "channel":
            frame["channels"].append(d)
        elif e.kind == "game_over":
            frame["game_over"] = True
        elif e.kind == "end":
            self.meta["end"] = d
            self._rules.end_tick()
        else:
            self._rules.apply(e, frame)
        self._rules.refresh(frame)

    def _frame(self, tick: int) -> dict[str, Any]:
        frame = {"tick": tick, "decisions": [], "messages": [], "channels": [],
                 "game_over": False,
                 **self._rules.new_frame()}
        self._rules.refresh(frame)
        return frame


def build_frames(events: list[Event]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    r = Replayer()
    r.feed(events)
    return r.meta, r.frames
