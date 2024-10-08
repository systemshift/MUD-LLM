import requests
from openai import OpenAI
import json
import numpy as np
from typing import List, Tuple
import time

BASE_URL = "http://localhost:5000"

client = OpenAI()

def print_game_state(game_state: str, game_info: str, debug_info: str):
    print("\nCurrent Game State:")
    print(game_state)
    print(game_info)
    print(f"Debug Info: {debug_info}")

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

def get_openai_command(game_state: str, game_info: str, last_move: str, valid_moves: List[str]) -> List[str]:
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
                                "enum": valid_moves
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

Use the provided function to make exactly 10 moves. Valid moves are: {', '.join(valid_moves)}.

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

Valid moves for your next action: {', '.join(valid_moves)}

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

    if response.choices[0].message.tool_calls:
        tool_call = response.choices[0].message.tool_calls[0]
        if tool_call.function.name == "make_moves":
            moves = json.loads(tool_call.function.arguments)["moves"]
            return moves
    
    print("Error: No valid function call in the response")
    return ["pass"] * 10

def search_next_n_steps(game_state: str, game_info: str, n: int = 10) -> List[str]:
    """
    Search for the next N steps and make commands based on the current game state.
    
    :param game_state: Current game state as a string
    :param game_info: Current game info as a string
    :param n: Number of steps to search ahead (default is 10)
    :return: List of commands for the next N steps
    """
    last_move = "None"
    game_array = parse_game_state(game_state)
    player_pos = get_player_position(game_array)
    valid_moves = get_valid_moves(game_array, player_pos)
    
    # Get the initial plan from OpenAI using function calling
    plan = get_openai_command(game_state, game_info, last_move, valid_moves)
    
    print(f"Initial plan: {plan}")
    
    # Ensure we have exactly N steps
    if len(plan) < n:
        plan.extend(["pass"] * (n - len(plan)))
    elif len(plan) > n:
        plan = plan[:n]
    
    return plan

def main():
    last_move = "None"
    move_counter = 0
    plan = []

    while True:
        # Get the current game state
        response = requests.get(f"{BASE_URL}/state")
        if response.status_code == 200:
            data = response.json()
            game_state = data["game_state"]
            game_info = data["game_info"]
            debug_info = data["debug_info"]
            print_game_state(game_state, game_info, debug_info)
        else:
            print(f"Error getting game state: {response.status_code}")
            break

        # Get command from search_next_n_steps if we don't have a plan or have exhausted the current plan
        if not plan:
            plan = search_next_n_steps(game_state, game_info)
            print(f"New plan: {plan}")

        # Execute the next move in the plan
        command = plan.pop(0)
        print(f"Executing command: {command}")

        if command in ["up", "down", "left", "right", "pass"]:
            response = requests.post(f"{BASE_URL}/move", json={"direction": command})
            last_move = command
        elif command == "bomb":
            response = requests.post(f"{BASE_URL}/bomb")
            last_move = "bomb"

        if response.status_code == 200:
            data = response.json()
            print(f"Move result: {data['success']}")
            print(f"Debug Info: {data['debug_info']}")
        else:
            print(f"Error: {response.status_code}")
            # Clear the plan if there's an error
            plan = []

        move_counter += 1
        if move_counter % 10 == 0:
            print(f"Completed 10 moves.")
            # Clear the plan to get a new one every 10 moves
            plan = []

        time.sleep(0.1)  # Add a small delay to prevent overwhelming the server

if __name__ == "__main__":
    print("Bomberman API Test with OpenAI")
    print("-------------------------------")
    main()