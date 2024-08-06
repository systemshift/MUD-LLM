import requests
from openai import OpenAI
import json

BASE_URL = "http://localhost:5000"

# Load OpenAI API key
with open("/home/decoy/MUD-LLM/bomberman/api", "r") as api_file:
    api_key = api_file.read().strip()

# Initialize OpenAI client
client = OpenAI(api_key=api_key)

def print_game_state(game_state, game_info, debug_info):
    print("\nCurrent Game State:")
    print(game_state)
    print(game_info)
    print(f"Debug Info: {debug_info}")

def get_openai_command(game_state, game_info, last_move, previous_thoughts):
    prompt = f"""
You are an AI agent playing a Bomberman game. Your objective is to destroy breakable stones and avoid explosions.
The game board is represented by:
'#' for walls (indestructible)
'S' for breakable stones
' ' for empty spaces
'P' for your current position
'B' for bombs

You can destroy breakable stones ('S') by placing bombs next to them.
Destroying stones gives you 10 points, but getting hit by an explosion costs 50 points.
Bombs explode after 3 moves, damaging stones and the player in a cross pattern with a range of 2.

Given the current game state, provide a plan for the next 10 moves to play the game strategically.
Valid commands are: up, down, left, right, bomb.

Current game state:
{game_state}

Game info:
{game_info}

Your last move was: {last_move}

Your previous thoughts:
{previous_thoughts}

Respond with a JSON object containing:
1. A list of 10 commands for your next moves.
2. Your thoughts on the current game state and strategy.

Example response:
{{
    "plan": ["up", "right", "bomb", "left", "down", "right", "up", "bomb", "left", "down"],
    "thoughts": "I plan to move towards the nearest breakable stone, place a bomb, and then move to safety. After that, I'll navigate to the next cluster of breakable stones."
}}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are an AI agent playing Bomberman. Provide a plan for the next 10 moves and your thoughts on the game strategy."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=300,
        n=1,
        stop=None,
        temperature=0.5,
    )

    response_content = response.choices[0].message.content.strip()
    try:
        command_data = json.loads(response_content)
        return command_data
    except json.JSONDecodeError:
        print("Error: Invalid JSON response from OpenAI")
        return {"plan": ["up"], "thoughts": "Error in parsing response"}

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

        if command in ["up", "down", "left", "right"]:
            response = requests.post(f"{BASE_URL}/move", json={"direction": command})
            last_move = command
        elif command == "bomb":
            response = requests.post(f"{BASE_URL}/bomb")
            last_move = "bomb"
        else:
            print("Invalid command from OpenAI. Skipping this turn.")
            continue
        
        if response.status_code == 200:
            data = response.json()
            print(f"Move result: {data['success']}")
            print(f"Debug Info: {data['debug_info']}")
        else:
            print(f"Error: {response.status_code}")

        move_counter += 1
        if move_counter % 10 == 0:
            print(f"Completed 10 moves. Previous thoughts: {previous_thoughts}")

if __name__ == "__main__":
    print("Bomberman API Test with OpenAI")
    print("-------------------------------")
    main()