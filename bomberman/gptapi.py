import requests
from openai import OpenAI
import json

BASE_URL = "http://localhost:5000"

# Load OpenAI API key
with open("/home/decoy/MUD-LLM/bomberman/api", "r") as api_file:
    api_key = api_file.read().strip()

# Initialize OpenAI client
client = OpenAI(api_key=api_key)

def game_state_to_grid(game_state):
    return [list(row) for row in game_state.split('\n')]

def find_player_position(grid):
    for y, row in enumerate(grid):
        for x, cell in enumerate(row):
            if cell == 'P':
                return (y, x)
    return None

def print_game_state(game_state, game_info, debug_info):
    print("\nCurrent Game State:")
    print(game_state)
    print(game_info)
    print(f"Debug Info: {debug_info}")

def is_valid_move(grid, player_pos, direction):
    y, x = player_pos
    dy, dx = {"up": (-1, 0), "down": (1, 0), "left": (0, -1), "right": (0, 1)}[direction]
    new_y, new_x = y + dy, x + dx
    if 0 <= new_y < len(grid) and 0 <= new_x < len(grid[0]):
        return grid[new_y][new_x] in [' ', 'P']
    return False

def get_openai_command(game_state, game_info, last_move, previous_thoughts):
    system_prompt = """
    You are an AI agent playing a Bomberman game. Your objective is to destroy breakable stones and avoid explosions.
    The game board is represented as a grid where:
    - The top-left corner is (0, 0)
    - Y-coordinate increases downwards
    - X-coordinate increases to the right
    - '#' are walls (indestructible)
    - 'S' are breakable stones
    - ' ' are empty spaces
    - 'P' is your current position
    - 'B' are bombs

    You can destroy breakable stones ('S') by placing bombs next to them.
    Destroying stones gives you 10 points, but getting hit by an explosion costs 50 points.
    Bombs explode after 3 moves, damaging stones and the player in a cross pattern with a range of 2.

    Valid commands are: up, down, left, right, bomb, pass.
    - 'up' decreases Y-coordinate
    - 'down' increases Y-coordinate
    - 'left' decreases X-coordinate
    - 'right' increases X-coordinate

    Provide a plan for the next 5 moves to play the game strategically.

    Respond with a JSON object containing:
    1. A list of 5 commands for your next moves.
    2. Your thoughts on the current game state and strategy.

    Example response:
    {
        "plan": ["up", "right", "bomb", "left", "down"],
        "thoughts": "I plan to move towards the nearest breakable stone, place a bomb, and then move to safety. After that, I'll navigate to the next cluster of breakable stones."
    }
    """

    grid = game_state_to_grid(game_state)
    player_pos = find_player_position(grid)
    height, width = len(grid), len(grid[0])

    user_prompt = f"""
    Current game state (grid size: {height}x{width}):
    {game_state}

    Your current position: {player_pos}
    Game info: {game_info}
    Your last move was: {last_move}

    Your previous thoughts:
    {previous_thoughts}

    Provide your next 5 moves and thoughts on the current game state and strategy.
    """

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
    try:
        command_data = json.loads(response_content)
        return command_data
    except json.JSONDecodeError:
        print("Error: Invalid JSON response from OpenAI")
        return {"plan": ["pass"], "thoughts": "Error in parsing response"}

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

        grid = game_state_to_grid(game_state)
        player_pos = find_player_position(grid)

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
            if is_valid_move(grid, player_pos, command):
                response = requests.post(f"{BASE_URL}/move", json={"direction": command})
                last_move = command
            else:
                print(f"Invalid move: {command}. Skipping this turn.")
                continue
        elif command == "bomb":
            response = requests.post(f"{BASE_URL}/bomb")
            last_move = "bomb"
        elif command == "pass":
            response = requests.post(f"{BASE_URL}/move", json={"direction": "pass"})
            last_move = "pass"
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
        if move_counter % 5 == 0:
            print(f"Completed 5 moves. Previous thoughts: {previous_thoughts}")
            plan = []  # Reset the plan every 5 moves

if __name__ == "__main__":
    print("Bomberman API Test with OpenAI")
    print("-------------------------------")
    main()