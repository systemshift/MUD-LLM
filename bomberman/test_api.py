import requests
from openai import OpenAI
import json

BASE_URL = "http://localhost:5000"

# Load OpenAI API key
with open("/home/decoy/MUD-LLM/bomberman/api", "r") as api_file:
    api_key = api_file.read().strip()

# Initialize OpenAI client
client = OpenAI(api_key=api_key)

def print_game_state(game_state):
    print("\nCurrent Game State:")
    print(game_state)

def get_openai_command(game_state, last_move):
    prompt = f"""
You are an AI agent playing a Bomberman game. Your mission is to reach the bottom right corner of the game board.
The game board is represented by '#' for walls, ' ' for empty spaces, and 'P' for your current position.
You need to move both down and right to reach the goal. If you can't move in one direction, try the other.
Do not try to move through walls or outside the game board.

Given the current game state, provide a single command to move towards your goal.
Valid commands are: up, down, left, right, bomb.

Current game state:
{game_state}

Your last move was: {last_move}

Respond with a single word command (up, down, left, or right):
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are an AI agent playing Bomberman. Provide a single command to move towards the bottom right corner."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=1,
        n=1,
        stop=None,
        temperature=0.5,
    )

    command = response.choices[0].message.content.strip().lower()
    return command

def main():
    last_move = "None"
    while True:
        # Get the current game state
        response = requests.get(f"{BASE_URL}/state")
        if response.status_code == 200:
            game_state = response.json()["game_state"]
            print_game_state(game_state)
        else:
            print(f"Error getting game state: {response.status_code}")
            break

        # Get command from OpenAI
        command = get_openai_command(game_state, last_move)
        print(f"OpenAI command: {command}")

        if command in ["up", "down", "left", "right"]:
            response = requests.post(f"{BASE_URL}/move", json={"direction": command})
            last_move = command
        elif command == "bomb":
            response = requests.post(f"{BASE_URL}/bomb")
            last_move = "bomb"
        else:
            print("Invalid command from OpenAI. Skipping this turn.")
            continue
        
        if response.status_code != 200:
            print(f"Error: {response.status_code}")

if __name__ == "__main__":
    print("Bomberman API Test with OpenAI")
    print("-------------------------------")
    main()