"""
Rebuild per-tick frames from a Bomberman event log.

Frame k is the state after tick k (frame 0 is the starting board), plus what
happened during that tick: explosions, hits, and agent decisions. The viewer
renders frames directly, so it never re-implements game rules.
"""

from typing import Any

from .games.bomberman import BombermanConfig
from .sim import Event


class Replayer:
    """Incremental: feed events as they arrive (live runs) and read frames."""

    def __init__(self):
        self.frames: list[dict[str, Any]] = []
        self.meta: dict[str, Any] = {}
        self._consumed = 0
        self._state: dict[str, Any] | None = None
        self._config = BombermanConfig()

    def feed(self, events: list[Event]):
        for e in events[self._consumed:]:
            self._apply(e)
        self._consumed = max(self._consumed, len(events))

    def _apply(self, e: Event):
        d = e.data
        if e.kind == "init":
            if "config" in d:
                self._config = BombermanConfig(**d["config"])
            self.meta.update(seed=d.get("seed"), config=d.get("config"))
            self._state = {
                "grid": [list(row) for row in d["grid"]],
                "players": {int(pid): {"pos": list(p["pos"]), "score": p["score"],
                                       "hits": p["hits"]} for pid, p in d["players"].items()},
                "bombs": [dict(b, pos=list(b["pos"])) for b in d["bombs"]],
            }
            self.frames = [self._frame(0)]
            return
        if e.kind == "meta":
            self.meta.update(d)
            return
        if self._state is None:
            return

        while self.frames[-1]["tick"] < e.tick:  # first event of a new tick
            self._advance_tick()
        frame, s = self.frames[-1], self._state

        if e.kind == "move":
            s["players"][d["player"]]["pos"] = list(d["to"])
        elif e.kind == "bomb_placed":
            # the engine already burned this tick's fuse by the end of the placing tick
            s["bombs"].append({"pos": list(d["pos"]), "owner": d["player"],
                               "fuse": self._config.bomb_fuse})
        elif e.kind == "explosion":
            s["bombs"] = [b for b in s["bombs"] if b["pos"] != list(d["pos"])]
            for r, c in d["stones"]:
                s["grid"][r][c] = " "
            if d["owner"] in s["players"]:
                s["players"][d["owner"]]["score"] += self._config.stone_points * len(d["stones"])
            frame["blasts"].append({"owner": d["owner"], "cells": d["cells"]})
        elif e.kind == "player_hit":
            p = s["players"][d["player"]]
            p["score"] += self._config.hit_penalty
            p["hits"] += 1
            frame["hits"].append(d["player"])
        elif e.kind == "decision":
            frame["decisions"].append(d)
        elif e.kind == "game_over":
            frame["game_over"] = True
        elif e.kind == "end":
            self.meta["end"] = d
        if e.kind in ("move_blocked", "bomb_failed"):
            frame["notes"].append(f"P{d['player']} {e.kind.replace('_', ' ')}")
        self._refresh(frame)

    def _advance_tick(self):
        """Start the next frame: fuses burn once per tick."""
        tick = self.frames[-1]["tick"] + 1
        for b in self._state["bombs"]:
            b["fuse"] -= 1
        self.frames.append(self._frame(tick))

    def _frame(self, tick: int) -> dict[str, Any]:
        frame = {"tick": tick, "blasts": [], "hits": [], "decisions": [], "notes": [],
                 "game_over": False}
        self._refresh(frame)
        return frame

    def _refresh(self, frame: dict[str, Any]):
        s = self._state
        frame["grid"] = ["".join(row) for row in s["grid"]]
        frame["players"] = {pid: dict(p, pos=list(p["pos"])) for pid, p in s["players"].items()}
        frame["bombs"] = [dict(b, pos=list(b["pos"])) for b in s["bombs"]]
        frame["stones"] = sum(row.count("S") for row in s["grid"])


def build_frames(events: list[Event]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    r = Replayer()
    r.feed(events)
    return r.meta, r.frames
