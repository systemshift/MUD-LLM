"""
Prompt Templates for LLM Agents
Centralized prompt management
"""


SYSTEM_PROMPT = """You are an expert AI agent playing Bomberman. Think strategically and CAREFULLY about positions.

COORDINATE SYSTEM (CRITICAL):
- Board uses (row, column) indexing where row=Y, column=X
- 'up' decreases row (Y), 'down' increases row (Y)
- 'left' decreases column (X), 'right' increases column (X)
- Your position (Y, X) means: Y rows down from top, X columns right from left

GAME SYMBOLS:
- '#' = Indestructible wall (CANNOT move through)
- 'S' = Breakable stone (target, but CANNOT move through until destroyed)
- ' ' = Empty space (CAN move here)
- 'P' or '1'/'2'/'3'/'4' = Player positions
- 'B' = Active bomb (DANGER! Will explode in 3 moves)

MOVEMENT RULES:
- You can ONLY move into spaces marked ' ' (empty)
- You CANNOT move through '#' walls or 'S' stones
- ALWAYS verify your next move is into an empty ' ' space

BOMB MECHANICS:
1. Bombs explode after EXACTLY 3 moves in a PLUS (+) pattern
2. Explosion extends 2 cells in all 4 directions (up/down/left/right)
3. Walls '#' block explosions, stones 'S' are destroyed by explosions
4. Getting hit by explosion = -50 points (VERY BAD)
5. Destroying a stone = +10 points

CRITICAL SAFETY RULES:
- After placing bomb, you MUST move at least 3 spaces away within 3 moves
- Count moves carefully: move 1, move 2, move 3 = BOOM!
- Don't place bomb if you're surrounded by walls/stones with no escape
- If there's an active bomb 'B', calculate if you're in danger zone

STRATEGY:
- Identify nearest accessible stone (reachable through empty spaces)
- Navigate to position next to stone
- Place bomb, then IMMEDIATELY retreat 3+ moves
- Only use 'pass' if waiting for explosion is strategically necessary"""


def get_user_prompt(game_state: str, game_info: str, player_pos: tuple,
                    surroundings: str, valid_moves: list, stones_info: str,
                    bombs_info: str, last_move: str) -> str:
    """Generate user prompt for LLM."""
    return f"""CURRENT GAME STATE:
{game_state}

YOUR POSITION: Row {player_pos[1]}, Column {player_pos[0]}

IMMEDIATE SURROUNDINGS (3x3 around you):
{surroundings}

GAME INFO: {game_info}
LAST MOVE: {last_move}

ANALYSIS:
- {stones_info}
- {bombs_info}
- Valid moves you can make: {', '.join(valid_moves)}

IMPORTANT:
- 'valid moves' list shows ONLY moves that lead to empty spaces ' '
- If a direction is missing, that means there's a wall '#' or stone 'S' blocking
- NEVER plan a move that's not in the valid moves list

TASK: Plan your next 10 moves carefully:
1. Look at your surroundings - which directions are open (empty ' ')?
2. Where is the nearest stone you can reach through open spaces?
3. Navigate there, place bomb, retreat to safety
4. Verify each move goes to an empty space

Use the make_moves function with your reasoning and 10 moves."""


def get_function_schema(valid_moves: list) -> dict:
    """Get function calling schema for LLM."""
    return {
        "type": "function",
        "function": {
            "name": "make_moves",
            "description": "Make a series of 10 strategic moves in the Bomberman game",
            "parameters": {
                "type": "object",
                "properties": {
                    "reasoning": {
                        "type": "string",
                        "description": "Your strategic reasoning for the next 10 moves"
                    },
                    "moves": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": valid_moves
                        },
                        "minItems": 10,
                        "maxItems": 10,
                        "description": "Exactly 10 moves to execute"
                    }
                },
                "required": ["reasoning", "moves"]
            }
        }
    }
