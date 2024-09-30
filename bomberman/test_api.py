import requests
from openai import OpenAI
import json
import re
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

def get_openai_command(game_state: str, game_info: str, last_move: str, previous_thoughts: str) -> dict:
    combined_prompt = f"""
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

Valid commands are: up, down, left, right, bomb, pass.

Provide a plan for the next 30 moves to play the game strategically.

Good moves:
- Moving towards the nearest stone to bomb it
- Placing a bomb next to multiple stones
- Moving away from a placed bomb

Bad moves:
- Walking into a bomb's explosion range
- Placing a bomb when surrounded by walls
- Moving away from the goal (bottom-right corner) without a good reason

Respond with a JSON object containing:
1. A list of 30 commands for your next moves.
2. Your thoughts on the current game state and strategy.

Example response:
{{
    "plan": ["right", "bomb", "left", "down", "pass", ...],  // 30 moves total
    "thoughts": "I'm moving right to place a bomb next to two stones, then retreating left and down to avoid the explosion. I'll continue to navigate the board, destroying stones and avoiding explosions."
}}

Current game state:
{game_state}

Game info:
{game_info}

Your last move was: {last_move}

Your previous thoughts:
{previous_thoughts}

Provide your next 30 moves and thoughts on the current game state and strategy.
"""

    response = client.chat.completions.create(
        model="o1-mini",
        messages=[
            {"role": "user", "content": combined_prompt}
        ],
        n=1
    )

    response_content = response.choices[0].message.content.strip()
    print("Raw OpenAI response:")
    print(response_content)
    print("End of raw response")

    # Extract JSON from the response
    json_match = re.search(r'\{.*\}', response_content, re.DOTALL)
    if json_match:
        try:
            command_data = json.loads(json_match.group())
            print("Successfully extracted JSON from the response.")
            return command_data
        except json.JSONDecodeError as json_error:
            print(f"Error: Invalid JSON in extracted content. JSON error: {str(json_error)}")
    else:
        print("Error: No valid JSON object found in the response.")

def main():
    last_move = "None"
    previous_thoughts = "No previous thoughts."
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

        # Get command from OpenAI if we don't have a plan or have exhausted the current plan
        if not plan:
            command_data = get_openai_command(game_state, game_info, last_move, previous_thoughts)
            plan = command_data["plan"]
            previous_thoughts = command_data["thoughts"]
            print(f"New plan: {plan}")
            print(f"Thoughts: {previous_thoughts}")

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
        if move_counter % 30 == 0:
            print(f"Completed 30 moves. Previous thoughts: {previous_thoughts}")
            # Clear the plan to get a new one every 30 moves
            plan = []

        time.sleep(0.1)  # Add a small delay to prevent overwhelming the server

if __name__ == "__main__":
    print("Bomberman API Test with OpenAI")
    print("-------------------------------")
    main()