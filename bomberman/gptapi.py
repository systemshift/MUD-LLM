from openai import OpenAI
import json
import time

BASE_URL = "http://localhost:5000"

client = OpenAI()

def print_game_state(game_state, game_info, debug_info):
    print("\nCurrent Game State:")
    print(game_state)
    print(game_info)
    print(f"Debug Info: {debug_info}")

def openai_command(game_state, game_info, last_move):
    tools = [
        {
            "type": "function",
            "function": {
                "name": "make_moves",
                "description": "Make a series of 10 moves in the Bomberman game",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "moves": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["up", "down", "left", "right", "pass", "bomb"]
                            },
                            "minItems": 10,
                            "maxItems": 10
                        }
                    },
                    "required": ["moves"]
                }
            }
        }
    ]

    messages = [
        {"role": "system", "content": f"""
You are an AI agent playing a Bomberman game. Your objective is to destroy breakable stones and avoid explosions.
The game board is represented by:
'#' for walls (indestructible)
'S' for breakable stones
' ' for empty spaces
'P' for your current position
'B' for bombs

Game mechanics:
1. You can destroy breakable stones ('S') by placing bombs next to them.
2. Destroying stones gives you 10 points, but getting hit by an explosion costs 50 points.
3. Bombs explode after 3 moves, damaging stones and the player in a cross pattern with a range of 2.

Good moves:
- Moving towards the nearest stone to bomb it
- Placing a bomb next to multiple stones
- Moving away from a placed bomb

Bad moves:
- Walking into a bomb's explosion range
- Placing a bomb when surrounded by walls
- Moving away from the goal (bottom-right corner) without a good reason
- Using 'pass' when there are better moves available

Remember to plan ahead for all 10 moves, considering the consequences of your actions and the game state changes.
        """},
        {"role": "user", "content": f"""
Current game state:
{game_state}

Game info:
{game_info}

Your last move was: {last_move}

Provide your next 10 moves using the make_moves function. Be strategic and avoid unnecessary 'pass' moves. Plan ahead for all 10 moves, considering how the game state will change after each action.
        """}
    ]

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        tools=tools,
        tool_choice="auto",
        max_tokens=500,
    )

