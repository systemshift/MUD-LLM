"""Fast control layer: turns intents into one primitive action per tick."""

from .base import Controller, Intent, Outcome
from .bomberman import BombermanController, danger_map, plan_path

__all__ = ["BombermanController", "Controller", "Intent", "Outcome", "danger_map", "plan_path"]
