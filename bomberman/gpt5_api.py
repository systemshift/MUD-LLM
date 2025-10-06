import requests
from openai import OpenAI
import json
import numpy as np
from typing import List, Tuple
import time
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

BASE_URL = "http://localhost:5000"

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def print_game_state(game_state: str, game_info: str, debug_info: str):
    print("\n" + "="*60)
    print("Current Game State:")
    print(game_state)
    print(game_info)
    print(f"Debug Info: {debug_info}")
    print("="*60)

def parse_game_state(game_state: str) -> np.ndarray:
    return np.array([list(row) for row in game_state.strip().split('\n')])

def get_player_position(game_state: np.ndarray) -> Tuple[int, int]:
    player_pos = np.where(game_state == 'P')
    return player_pos[0][0], player_pos[1][0]

def get_valid_moves(game_state: np.ndarray, player_pos: Tuple[int, int]) -> List[str]:
    valid_moves = []
    directions = [('up', (-1, 0)), ('down', (1, 0)), ('left', (0, -1)), ('right', (0, 1))]
    for direction, (dy, dx) in directions:
        new_y, new_x = player_pos[0] + dy, player_pos[1] + dx
        if 0 <= new_y < game_state.shape[0] and 0 <= new_x < game_state.shape[1]:
            if game_state[new_y, new_x] in [' ', 'S']:
                valid_moves.append(direction)
    valid_moves.extend(['bomb', 'pass'])
    return valid_moves

def get_stones_info(game_state: np.ndarray, player_pos: Tuple[int, int]) -> str:
    """Get information about nearby breakable stones."""
    stones = np.where(game_state == 'S')
    if len(stones[0]) == 0:
        return "No breakable stones remaining."

    stone_positions = list(zip(stones[0], stones[1]))
    distances = [abs(s[0] - player_pos[0]) + abs(s[1] - player_pos[1]) for s in stone_positions]
    nearest_dist = min(distances)
    stone_count = len(stone_positions)

    return f"Total stones: {stone_count}. Nearest stone is {nearest_dist} moves away."

def get_bombs_info(game_state: np.ndarray, player_pos: Tuple[int, int]) -> str:
    """Get information about active bombs."""
    bombs = np.where(game_state == 'B')
    if len(bombs[0]) == 0:
        return "No active bombs."

    bomb_positions = list(zip(bombs[0], bombs[1]))
    distances = [abs(b[0] - player_pos[0]) + abs(b[1] - player_pos[1]) for b in bomb_positions]
    nearest_bomb_dist = min(distances)

    return f"{len(bomb_positions)} active bomb(s). Nearest bomb is {nearest_bomb_dist} moves away. DANGER: Bombs explode after 3 moves with range 2!"

def get_o4_mini_command(game_state: str, game_info: str, last_move: str, valid_moves: List[str]) -> Tuple[List[str], str]:
    """Get commands from o4-mini with reasoning."""

    game_array = parse_game_state(game_state)
    player_pos = get_player_position(game_array)
    stones_info = get_stones_info(game_array, player_pos)
    bombs_info = get_bombs_info(game_array, player_pos)

    # Get surrounding context (3x3 grid around player)
    py, px = player_pos
    surroundings = []
    for dy in [-1, 0, 1]:
        row = []
        for dx in [-1, 0, 1]:
            ny, nx = py + dy, px + dx
            if 0 <= ny < game_array.shape[0] and 0 <= nx < game_array.shape[1]:
                cell = game_array[ny, nx]
                if dy == 0 and dx == 0:
                    row.append('[P]')
                else:
                    row.append(f'[{cell}]')
            else:
                row.append('[#]')
        surroundings.append(' '.join(row))
    surroundings_str = '\n'.join(surroundings)

    tools = [
        {
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
    ]

    messages = [
        {"role": "system", "content": """You are an expert AI agent playing Bomberman. Think strategically and CAREFULLY about positions.

COORDINATE SYSTEM (CRITICAL):
- Board uses (row, column) indexing where row=Y, column=X
- 'up' decreases row (Y), 'down' increases row (Y)
- 'left' decreases column (X), 'right' increases column (X)
- Your position (Y, X) means: Y rows down from top, X columns right from left

GAME SYMBOLS:
- '#' = Indestructible wall (CANNOT move through)
- 'S' = Breakable stone (target, but CANNOT move through until destroyed)
- ' ' = Empty space (CAN move here)
- 'P' = Your current position
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
- Only use 'pass' if waiting for explosion is strategically necessary"""},
        {"role": "user", "content": f"""CURRENT GAME STATE:
{game_state}

YOUR POSITION: Row {player_pos[0]}, Column {player_pos[1]}

IMMEDIATE SURROUNDINGS (3x3 around you):
{surroundings_str}

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

Use the make_moves function with your reasoning and 10 moves."""}
    ]

    try:
        response = client.chat.completions.create(
            model="gpt-5",
            messages=messages,
            tools=tools,
            tool_choice={"type": "function", "function": {"name": "make_moves"}},
        )

        if response.choices[0].message.tool_calls:
            tool_call = response.choices[0].message.tool_calls[0]
            if tool_call.function.name == "make_moves":
                result = json.loads(tool_call.function.arguments)
                reasoning = result.get("reasoning", "No reasoning provided")
                moves = result.get("moves", [])

                # Validate moves
                if len(moves) != 10:
                    print(f"⚠️  WARNING: Got {len(moves)} moves, expected 10. Padding with 'pass'.")
                    moves = (moves + ["pass"] * 10)[:10]

                return moves, reasoning

        print("❌ ERROR: No valid function call in response")
        return ["pass"] * 10, "Error: No response"

    except Exception as e:
        print(f"❌ API ERROR: {e}")
        return ["pass"] * 10, f"Error: {e}"

def main():
    last_move = "None"
    move_counter = 0
    plan = []
    reasoning = ""
    total_score = 0

    print("🎮 Bomberman with GPT-5 Model")
    print("=" * 60)

    while True:
        # Get current game state
        try:
            response = requests.get(f"{BASE_URL}/state")
            if response.status_code == 200:
                data = response.json()
                game_state = data["game_state"]
                game_info = data["game_info"]
                debug_info = data["debug_info"]
                print_game_state(game_state, game_info, debug_info)
            else:
                print(f"❌ Error getting game state: {response.status_code}")
                break
        except Exception as e:
            print(f"❌ Connection error: {e}")
            print("💡 Make sure the Flask server is running: python bomberman/api.py")
            break

        # Get new plan if needed
        if not plan:
            print("\n🤔 GPT-5 is thinking...")
            plan, reasoning = get_o4_mini_command(game_state, game_info, last_move,
                                                  get_valid_moves(parse_game_state(game_state),
                                                                 get_player_position(parse_game_state(game_state))))
            print(f"\n💭 REASONING: {reasoning}")
            print(f"📋 PLAN: {plan}\n")

        # Execute next move
        command = plan.pop(0)
        print(f"▶️  Executing move {move_counter + 1}: {command}")

        if command in ["up", "down", "left", "right", "pass"]:
            response = requests.post(f"{BASE_URL}/move", json={"direction": command})
            last_move = command
        elif command == "bomb":
            response = requests.post(f"{BASE_URL}/bomb")
            last_move = "bomb"
        else:
            print(f"⚠️  Invalid command '{command}', using 'pass'")
            response = requests.post(f"{BASE_URL}/move", json={"direction": "pass"})
            last_move = "pass"

        if response.status_code == 200:
            data = response.json()
            print(f"✅ Success: {data['success']}")
        else:
            print(f"❌ Error: {response.status_code}")
            plan = []  # Clear plan on error

        move_counter += 1

        # Get new plan every 10 moves
        if move_counter % 10 == 0:
            print(f"\n📊 Completed {move_counter} moves. Getting new plan...\n")
            plan = []

        time.sleep(0.15)  # Slight delay for readability

if __name__ == "__main__":
    main()
