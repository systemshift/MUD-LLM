from flask import Flask, render_template, jsonify
from game import Board, Player

app = Flask(__name__)

# Initialize the game
board = Board(32, 32)  # Default size, can be changed later
players = []

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/game_state')
def game_state():
    state = {
        'board': str(board),
        'players': [{'id': p.id, 'x': p.x, 'y': p.y} for p in players]
    }
    return jsonify(state)

if __name__ == '__main__':
    app.run(debug=True)