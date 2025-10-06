"""
Bomberman Multi-Player Game Server
Flask API server with configurable game settings
"""
from flask import Flask, jsonify, request
from game_multiplayer import MultiPlayerGame
from config import (
    SERVER_HOST, SERVER_PORT, DEBUG_MODE,
    NUM_PLAYERS, BOARD_WIDTH, BOARD_HEIGHT
)

app = Flask(__name__)

# Global game instance
game = None


def init_game(num_players: int = NUM_PLAYERS, width: int = BOARD_WIDTH,
              height: int = BOARD_HEIGHT):
    """Initialize a new game with specified parameters."""
    global game
    game = MultiPlayerGame(num_players=num_players, width=width, height=height)
    print(f"🎮 Game initialized: {num_players} player(s), {width}x{height} board")
    return game


@app.route('/init', methods=['POST'])
def init_game_endpoint():
    """Initialize a new game with custom settings."""
    data = request.json or {}
    num_players = data.get('num_players', NUM_PLAYERS)
    width = data.get('width', BOARD_WIDTH)
    height = data.get('height', BOARD_HEIGHT)

    init_game(num_players, width, height)

    return jsonify({
        "success": True,
        "num_players": game.num_players,
        "board_size": (width, height),
        "message": f"Game initialized with {num_players} players"
    })


@app.route('/move/<int:player_id>', methods=['POST'])
def move(player_id):
    """Move a specific player."""
    if game is None:
        return jsonify({"error": "Game not initialized"}), 400

    direction = request.json.get('direction')
    if direction not in ['up', 'down', 'left', 'right', 'pass']:
        return jsonify({"error": "Invalid direction"}), 400

    success = game.move_player(player_id, direction)

    return jsonify({
        "success": success,
        "player_id": player_id,
        "game_state": game.get_game_state(),
        "game_info": game.get_game_info(),
        "player_info": game.get_player_info(player_id)
    })


@app.route('/bomb/<int:player_id>', methods=['POST'])
def bomb(player_id):
    """Place a bomb for a specific player."""
    if game is None:
        return jsonify({"error": "Game not initialized"}), 400

    success = game.place_bomb(player_id)

    return jsonify({
        "success": success,
        "player_id": player_id,
        "game_state": game.get_game_state(),
        "game_info": game.get_game_info(),
        "player_info": game.get_player_info(player_id)
    })


@app.route('/state', methods=['GET'])
def state():
    """Get current game state (global view)."""
    if game is None:
        return jsonify({"error": "Game not initialized"}), 400

    return jsonify({
        "game_state": game.get_game_state(),
        "game_info": game.get_game_info(),
        "all_players": game.get_all_players_info(),
        "move_count": game.move_counter
    })


@app.route('/state/<int:player_id>', methods=['GET'])
def player_state(player_id):
    """Get game state from a specific player's perspective."""
    if game is None:
        return jsonify({"error": "Game not initialized"}), 400

    if player_id not in game.players:
        return jsonify({"error": f"Player {player_id} does not exist"}), 404

    return jsonify({
        "game_state": game.get_game_state(player_id),
        "game_info": game.get_game_info(player_id),
        "player_info": game.get_player_info(player_id),
        "debug_info": f"Player {player_id} at ({game.players[player_id].x}, {game.players[player_id].y})"
    })


@app.route('/players', methods=['GET'])
def players():
    """Get information about all players."""
    if game is None:
        return jsonify({"error": "Game not initialized"}), 400

    return jsonify({
        "num_players": game.num_players,
        "players": game.get_all_players_info()
    })


@app.route('/reset', methods=['POST'])
def reset():
    """Reset the game with same settings."""
    if game is None:
        return jsonify({"error": "Game not initialized"}), 400

    init_game(game.num_players, game.board.width, game.board.height)

    return jsonify({
        "success": True,
        "message": "Game reset"
    })


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "game_active": game is not None,
        "num_players": game.num_players if game else 0
    })


if __name__ == '__main__':
    # Initialize game on startup
    init_game()

    print(f"🚀 Bomberman Server starting on {SERVER_HOST}:{SERVER_PORT}")
    print(f"📊 Configuration: {NUM_PLAYERS} player(s), {BOARD_WIDTH}x{BOARD_HEIGHT} board")
    print(f"💡 Endpoints:")
    print(f"   - GET  /state - Get game state")
    print(f"   - GET  /state/<player_id> - Get player-specific state")
    print(f"   - POST /move/<player_id> - Move player")
    print(f"   - POST /bomb/<player_id> - Place bomb")
    print(f"   - POST /init - Initialize new game")
    print(f"   - POST /reset - Reset game")

    app.run(host=SERVER_HOST, port=SERVER_PORT, debug=DEBUG_MODE)
