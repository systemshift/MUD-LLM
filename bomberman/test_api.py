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

def get_nearest_stone(game_state: np.ndarray, player_pos: Tuple[int, int]) -> Tuple[int, int]:
    stones = np.where(game_state == 'S')
    if len(stones[0]) == 0:
        return None
    distances = np.sqrt((stones[0] - player_pos[0])**2 + (stones[1] - player_pos[1])**2)
    nearest_index = np.argmin(distances)
    return stones[0][nearest_index], stones[1][nearest_index]

def simple_rule_based_move(game_state: np.ndarray, player_pos: Tuple[int, int]) -> str:
    nearest_stone = get_nearest_stone(game_state, player_pos)
    if nearest_stone is None:
        return "pass"
    
    dy, dx = nearest_stone[0] - player_pos[0], nearest_stone[1] - player_pos[1]
    
    if abs(dy) > abs(dx):
        return "down" if dy > 0 else "up"
    else:
        return "right" if dx > 0 else "left"

def get_openai_command(game_state: str, game_info: str, last_move: str, previous_thoughts: str) -> dict:
    system_prompt = """
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

Provide a plan for the next 5 moves to play the game strategically.

Good moves:
- Moving towards the nearest stone to bomb it
- Placing a bomb next to multiple stones
- Moving away from a placed bomb

Bad moves:
- Walking into a bomb's explosion range
- Placing a bomb when surrounded by walls
- Moving away from the goal (bottom-right corner) without a good reason

Respond with a JSON object containing:
1. A list of 5 commands for your next moves.
2. Your thoughts on the current game state and strategy.

Example response:
{
    "plan": ["right", "bomb", "left", "down", "pass"],
    "thoughts": "I'm moving right to place a bomb next to two stones, then retreating left and down to avoid the explosion. I'll wait one turn for the bomb to explode before proceeding."
}
"""

    user_prompt = f"""
Current game state:
{game_state}

Game info:
{game_info}

Your last move was: {last_move}

Your previous thoughts:
{previous_thoughts}

Provide your next 5 moves and thoughts on the current game state and strategy.
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=300,
            n=1,
            stop=None,
            temperature=0.5,
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

        # If JSON extraction fails, attempt to parse the entire response
        try:
            command_data = json.loads(response_content)
            return command_data
        except json.JSONDecodeError as json_error:
            print(f"Error: Invalid JSON in entire response. JSON error: {str(json_error)}")

        # If all parsing attempts fail, use rule-based system
        game_state_array = parse_game_state(game_state)
        player_pos = get_player_position(game_state_array)
        rule_based_move = simple_rule_based_move(game_state_array, player_pos)
        return {"plan": [rule_based_move], "thoughts": "Using rule-based system due to parsing error."}

    except Exception as e:
        print(f"Error: Failed to get response from OpenAI. Error: {str(e)}")
        # Use rule-based system as fallback
        game_state_array = parse_game_state(game_state)
        player_pos = get_player_position(game_state_array)
        rule_based_move = simple_rule_based_move(game_state_array, player_pos)
        return {"plan": [rule_based_move], "thoughts": "Using rule-based system due to API error."}

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
        else:
            print("Invalid command. Using rule-based system.")
            game_state_array = parse_game_state(game_state)
            player_pos = get_player_position(game_state_array)
            command = simple_rule_based_move(game_state_array, player_pos)
            response = requests.post(f"{BASE_URL}/move", json={"direction": command})
            last_move = command

        if response.status_code == 200:
            data = response.json()
            print(f"Move result: {data['success']}")
            print(f"Debug Info: {data['debug_info']}")
        else:
            print(f"Error: {response.status_code}")
            # Clear the plan if there's an error
            plan = []

        move_counter += 1
        if move_counter % 5 == 0:
            print(f"Completed 5 moves. Previous thoughts: {previous_thoughts}")
            # Clear the plan to get a new one every 5 moves
            plan = []

        time.sleep(0.1)  # Add a small delay to prevent overwhelming the server

if __name__ == "__main__":
    print("Bomberman API Test with OpenAI")
    print("-------------------------------")
    main()