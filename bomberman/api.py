from flask import Flask, jsonify, request
from game import Game

app = Flask(__name__)
game = Game()

@app.route('/move', methods=['POST'])
def move():
    direction = request.json.get('direction')
    if direction not in ['up', 'down', 'left', 'right']:
        return jsonify({"error": "Invalid direction"}), 400
    success = game.move_player(direction)
    return jsonify({
        "success": success,
        "game_state": game.get_game_state(),
        "game_info": game.get_game_info(),
        "debug_info": f"Player position: ({game.player.x}, {game.player.y})"
    })

@app.route('/bomb', methods=['POST'])
def bomb():
    success = game.place_bomb()
    return jsonify({
        "success": success,
        "game_state": game.get_game_state(),
        "game_info": game.get_game_info(),
        "debug_info": f"Player position: ({game.player.x}, {game.player.y})"
    })

@app.route('/state', methods=['GET'])
def state():
    return jsonify({
        "game_state": game.get_game_state(),
        "game_info": game.get_game_info(),
        "debug_info": f"Player position: ({game.player.x}, {game.player.y})"
    })

if __name__ == '__main__':
    app.run(debug=True)