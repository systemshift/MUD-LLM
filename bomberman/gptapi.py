from openai import OpenAI
import json
import time
import requests
from game_state_processor import GameStateProcessor

BASE_URL = "http://localhost:5000"

client = OpenAI()
game_processor = GameStateProcessor()

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

Your moves will be determined by a game state processor. Your role is to analyze the game state and provide strategic insights.
        """},
        {"role": "user", "content": f"""
Current game state:
{game_state}

Game info:
{game_info}

Your last move was: {last_move}

Analyze the current game state and provide strategic insights. The game state processor will determine the actual moves.
        """}
    ]

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        tools=tools,
        tool_choice="auto",
        max_tokens=500,
    )

    # Process the game state and get the moves
    suggested_moves = game_processor.process_game_state(game_state, game_info)

    # Create a function call with the processed moves
    function_call = {
        "name": "make_moves",
        "arguments": json.dumps({"moves": suggested_moves})
    }

    return response.choices[0].message, function_call

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

        # Get command from openai_command if we don't have a plan or have exhausted the current plan
        if not plan:
            _, function_call = openai_command(game_state, game_info, last_move)
            if function_call["name"] == "make_moves":
                plan = json.loads(function_call["arguments"])["moves"]
                print(f"New plan: {plan}")
            else:
                print("Error: No valid function call in the response")
                break

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

        # Check if the game is over
        if "Game Over" in game_info:
            print("Game Over!")
            break

if __name__ == "__main__":
    print("Bomberman GPT API with Game State Processor")
    print("-------------------------------------------")
    main()
