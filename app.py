from flask import Flask, render_template
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app)

# Global game state
game_state = [['' for _ in range(3)] for _ in range(3)]
players = {"X": None, "O": None}

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('send_message')
def handle_message(data):
    emit('receive_message', data, broadcast=True)

@socketio.on('make_move')
def handle_move(data):
    x, y, player = data['x'], data['y'], data['player']
    if game_state[x][y] == '':
        game_state[x][y] = player
        next_player = 'O' if player == 'X' else 'X'
        emit('move_made', {'x': x, 'y': y, 'player': player, 'next_player': next_player}, broadcast=True)
        check_winner(player)

def check_winner(player):
    wins = [
        [game_state[0][0], game_state[0][1], game_state[0][2]],
        [game_state[1][0], game_state[1][1], game_state[1][2]],
        [game_state[2][0], game_state[2][1], game_state[2][2]],
        [game_state[0][0], game_state[1][0], game_state[2][0]],
        [game_state[0][1], game_state[1][1], game_state[2][1]],
        [game_state[0][2], game_state[1][2], game_state[2][2]],
        [game_state[0][0], game_state[1][1], game_state[2][2]],
        [game_state[2][0], game_state[1][1], game_state[0][2]]
    ]
    for line in wins:
        if line == [player, player, player]:
            emit('game_won', {'winner': player}, broadcast=True)
            reset_game()
            break

def reset_game():
    global game_state
    game_state = [['' for _ in range(3)] for _ in range(3)]
    emit('reset_board', broadcast=True)

if __name__ == '__main__':
    socketio.run(app, debug=True)
