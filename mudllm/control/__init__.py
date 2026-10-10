"""Fast control layer: turns intents into one primitive action per tick."""

from .bomberman import Controller, Intent, Outcome, danger_map, plan_path

__all__ = ["Controller", "Intent", "Outcome", "danger_map", "plan_path"]
