from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# Store the game state and chat messages
game_state = [['' for _ in range(3)] for _ in range(3)]
chat_messages = []

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/move', methods=['POST'])
def move():
    data = request.get_json()
    row, col, player = data['row'], data['col'], data['player']
    if game_state[row][col] == '':
        game_state[row][col] = player
        return jsonify({'status': 'success', 'game_state': game_state})
    return jsonify({'status': 'fail', 'message': 'Invalid move'})

@app.route('/chat', methods=['POST'])
def chat():
    message = request.get_json()['message']
    chat_messages.append(message)
    return jsonify({'status': 'success', 'messages': chat_messages})

@app.route('/get_game_state')
def get_game_state():
    return jsonify({'game_state': game_state})

@app.route('/get_chat_messages')
def get_chat_messages():
    return jsonify({'messages': chat_messages})

if __name__ == '__main__':
    app.run(debug=True)
