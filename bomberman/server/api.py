"""
Flask REST API Server
Clean HTTP interface for game engine
"""
from flask import Flask, jsonify, request
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.engine import GameEngine
from config import SERVER_HOST, SERVER_PORT, DEBUG_MODE, NUM_PLAYERS, BOARD_WIDTH, BOARD_HEIGHT

app = Flask(__name__)
game: GameEngine = None


@app.route('/init', methods=['POST'])
def init():
    """Initialize new game."""
    global game
    data = request.json or {}
    num_players = data.get('num_players', NUM_PLAYERS)
    width = data.get('width', BOARD_WIDTH)
    height = data.get('height', BOARD_HEIGHT)

    game = GameEngine(num_players, width, height)

    return jsonify({
        'success': True,
        'num_players': game.num_players,
        'board_size': (width, height)
    })


@app.route('/move', methods=['POST'])
def move():
    """Move player (supports both /move and /move/<player_id>)."""
    if game is None:
        return jsonify({'error': 'Game not initialized'}), 400

    player_id = request.json.get('player_id', 1)
    direction = request.json.get('direction')

    if direction not in ['up', 'down', 'left', 'right', 'pass']:
        return jsonify({'error': 'Invalid direction'}), 400

    success = game.move_player(player_id, direction)

    return jsonify({
        'success': success,
        'game_state': game.get_state_string(),
        'game_info': game.get_game_info(player_id),
        'player_info': game.get_player_info(player_id),
        'debug_info': f"Player {player_id} at {game.players[player_id].get_position()}" if player_id in game.players else "Player not found"
    })


@app.route('/bomb', methods=['POST'])
def bomb():
    """Place bomb."""
    if game is None:
        return jsonify({'error': 'Game not initialized'}), 400

    player_id = request.json.get('player_id', 1)
    success = game.place_bomb(player_id)

    return jsonify({
        'success': success,
        'game_state': game.get_state_string(),
        'game_info': game.get_game_info(player_id),
        'player_info': game.get_player_info(player_id),
        'debug_info': f"Player {player_id} at {game.players[player_id].get_position()}" if player_id in game.players else "Player not found"
    })


@app.route('/state', methods=['GET'])
def state():
    """Get current game state."""
    if game is None:
        return jsonify({'error': 'Game not initialized'}), 400

    return jsonify({
        'game_state': game.get_state_string(),
        'game_info': game.get_game_info(),
        'all_players': game.get_all_players_info(),
        'move_count': game.move_count
    })


@app.route('/state/<int:player_id>', methods=['GET'])
def player_state(player_id):
    """Get state for specific player."""
    if game is None:
        return jsonify({'error': 'Game not initialized'}), 400

    if player_id not in game.players:
        return jsonify({'error': f'Player {player_id} not found'}), 404

    player = game.players[player_id]
    return jsonify({
        'game_state': game.get_state_string(),
        'game_info': game.get_game_info(player_id),
        'player_info': game.get_player_info(player_id),
        'debug_info': f"Player {player_id} at ({player.x}, {player.y})"
    })


@app.route('/reset', methods=['POST'])
def reset():
    """Reset game."""
    global game
    if game is None:
        return jsonify({'error': 'Game not initialized'}), 400

    game.reset()
    return jsonify({'success': True})


@app.route('/health', methods=['GET'])
def health():
    """Health check."""
    return jsonify({
        'status': 'healthy',
        'game_initialized': game is not None,
        'num_players': game.num_players if game else 0
    })


def start_server(num_players: int = NUM_PLAYERS, width: int = BOARD_WIDTH,
                 height: int = BOARD_HEIGHT, host: str = SERVER_HOST,
                 port: int = SERVER_PORT):
    """Start server with game initialized."""
    global game
    game = GameEngine(num_players, width, height)

    print(f"🚀 Bomberman Server")
    print(f"   Players: {num_players}")
    print(f"   Board: {width}x{height}")
    print(f"   URL: http://{host}:{port}")
    print("="*50)

    app.run(host=host, port=port, debug=DEBUG_MODE)


if __name__ == '__main__':
    start_server()
