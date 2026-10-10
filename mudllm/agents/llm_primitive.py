"""
LLM plans primitive actions itself (no controller). Port of the v0-legacy agent,
kept as a capability benchmark: how well can a model drive every keypress?
"""

from ..games.bomberman import ACTIONS, BombermanConfig, Observation
from ..games.bomberman.text import describe_observation
from .providers import Usage
from .providers.openai import function_tool

MAX_PLAN = 10


def system_prompt(config: BombermanConfig) -> str:
    return f"""You are playing a turn-based Bomberman game. Your goal is to destroy every breakable stone as efficiently as possible without getting caught in your own explosions.

BOARD
- Cells are (row, col). Row 0 is the top, col 0 is the left.
- 'up' = row-1, 'down' = row+1, 'left' = col-1, 'right' = col+1.
- '#' wall, 'S' breakable stone, ' ' floor, 'B' bomb, 'P' you, digits are other players.
- You can only step onto floor (bombs do not block movement). Moving into '#' or 'S' fails and wastes the tick.
- A bomb you stand on is hidden under 'P'; the "Active bombs" line always lists every bomb.

TIME
- Every action (move, bomb, pass, or a failed move) is exactly one tick.

BOMBS
- 'bomb' places a bomb on your cell. You may have several bombs out at once.
- A bomb explodes at the end of the {config.bomb_fuse}rd tick AFTER the one that placed it.
  Example: bomb, a1, a2, a3 -> the explosion happens right after a3. Wherever you stand after a3 must be safe.
- "explodes in N tick(s)" means it goes off at the end of the Nth tick from now.
- The blast hits the bomb's cell and {config.bomb_range} cells up, down, left and right.
  '#' stops a ray. 'S' is destroyed and also stops that ray. Rays do not turn corners.
- Each stone destroyed: +{config.stone_points}. Standing in any blast cell when it goes off: {config.hit_penalty}.

PLANNING
- Submit 1 to {MAX_PLAN} actions via make_moves. They run in order, then you get the new board and plan again.
- If any action fails, the rest of the plan is discarded and you replan, so short precise plans beat long guesses.
- Before submitting, trace your plan cell by cell: confirm every step lands on floor and that you are out of every blast zone when each bomb goes off.
- Avoid 'pass' unless you are deliberately waiting in a safe cell."""


TOOL = function_tool("make_moves", f"Submit the next 1-{MAX_PLAN} actions to execute in order.", {
    "reasoning": {"type": "string", "description": "Brief plan: target stone, bomb cell, escape cell."},
    "moves": {"type": "array", "items": {"type": "string", "enum": list(ACTIONS)}},
})


class LLMPrimitivePolicy:
    def __init__(self, config: BombermanConfig, provider):
        self.provider = provider
        self.instructions = system_prompt(config)
        self.name = f"llm-primitive:{provider.model}"
        self.usage = Usage()
        self.last_result = "None (first turn)"

    def feedback(self, planned: list[str], executed: int, failed: str | None):
        if failed:
            self.last_result = (f"{planned} -> executed {executed}, then '{failed}' FAILED; "
                                f"remaining actions discarded.")
        else:
            self.last_result = f"{planned} -> all {executed} executed."

    def plan(self, obs: Observation) -> list[str]:
        prompt = f"{describe_observation(obs)}\nLast plan result: {self.last_result}\n\nCall make_moves."
        try:
            completion = self.provider.complete(
                self.instructions, [{"role": "user", "content": prompt}], [TOOL],
                tool_choice={"type": "function", "name": "make_moves"}, parallel_tool_calls=False)
        except Exception:
            self.usage.errors += 1
            return ["pass"]
        self.usage.add(completion.usage)
        for call in completion.tool_calls:
            moves = [m for m in call.arguments.get("moves", []) if m in ACTIONS][:MAX_PLAN]
            if moves:
                return moves
        return ["pass"]
