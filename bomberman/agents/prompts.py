"""
Prompt Templates for LLM Agents
Centralized prompt management
"""

from ..config import BOMB_TIMER, BOMB_RANGE, STONE_DESTROY_POINTS, EXPLOSION_HIT_PENALTY, MOVES_PER_PLAN

ACTIONS = ["up", "down", "left", "right", "bomb", "pass"]

SYSTEM_PROMPT = f"""You are playing a turn-based Bomberman game. Your goal is to destroy every breakable stone as efficiently as possible without getting caught in your own explosions.

BOARD
- Grid cells are addressed as (row, col). Row 0 is the top, col 0 is the left.
- 'up' = row-1, 'down' = row+1, 'left' = col-1, 'right' = col+1.
- '#' indestructible wall, 'S' breakable stone, ' ' empty floor, 'B' bomb, 'P' or a digit = player.
- You can only step onto empty floor (bombs do not block movement). Moving into '#' or 'S' fails and wastes the action.
- A bomb you are standing on is hidden under your 'P'; the "Active bombs" line always lists every bomb.

TIME
- Every action you take (move, bomb, pass, or a failed move) advances the clock by exactly one tick.

BOMBS
- 'bomb' places a bomb on your current cell. You may have several bombs out at once.
- A bomb explodes at the end of the {BOMB_TIMER}rd action AFTER the one that placed it.
  Example: bomb, a1, a2, a3 -> the explosion happens right after a3 resolves. Wherever you stand after a3 must be safe.
- The explosion hits the bomb's cell and extends {BOMB_RANGE} cells up, down, left and right.
  '#' stops a ray. 'S' is destroyed and also stops that ray. Rays do not turn corners.
- Each stone destroyed: +{STONE_DESTROY_POINTS}. Standing in any explosion cell when it goes off: {EXPLOSION_HIT_PENALTY}.

PLANNING
- Submit a plan of 1 to {MOVES_PER_PLAN} actions via make_moves. They run in order, then you get the new board and plan again.
- If any action fails, the rest of the plan is discarded and you replan from the new state, so short precise plans beat long guesses.
- Before submitting, trace your plan cell by cell on the grid: confirm every step lands on empty floor and that you are out of every blast zone when each bomb goes off.
- Avoid 'pass' unless you are deliberately waiting in a safe cell for a bomb to clear a path."""


def format_board(game_state: str) -> str:
    """Render the board with row/col indices so coordinates can be read off directly."""
    rows = game_state.strip('\n').split('\n')
    width = max(len(r) for r in rows)
    tens = "     " + "".join(str(c // 10) if c >= 10 else " " for c in range(width))
    ones = "     " + "".join(str(c % 10) for c in range(width))
    body = [f"{r:>3}  {row}" for r, row in enumerate(rows)]
    return "\n".join([tens, ones] + body)


def get_user_prompt(game_state: str, game_info: str, player_pos: tuple,
                    open_moves: list, last_result: str) -> str:
    """Generate user prompt for LLM."""
    return f"""BOARD (row numbers on the left, column numbers on top):
{format_board(game_state)}

YOU: row {player_pos[1]}, col {player_pos[0]}
{game_info}
Directions open from your cell right now: {', '.join(open_moves) or 'none'}
Last plan result: {last_result}

Plan your next actions and call make_moves."""


def get_function_schema() -> dict:
    """Responses API function tool definition."""
    return {
        "type": "function",
        "name": "make_moves",
        "description": f"Submit the next 1-{MOVES_PER_PLAN} actions to execute in order.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "reasoning": {
                    "type": "string",
                    "description": "Brief plan: target stone, bomb cell, escape cell."
                },
                "moves": {
                    "type": "array",
                    "items": {"type": "string", "enum": ACTIONS},
                    "description": f"1 to {MOVES_PER_PLAN} actions, executed in order"
                }
            },
            "required": ["reasoning", "moves"],
            "additionalProperties": False
        }
    }
