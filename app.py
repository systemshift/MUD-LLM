from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room, leave_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'
socketio = SocketIO(app)

# Routes
@app.route('/')
def index():
    return render_template('index.html')

# SocketIO events
@socketio.on('message')
def handle_message(data):
    emit('message', data, broadcast=True)

@socketio.on('move')
def handle_move(data):
    emit('move', data, broadcast=True)

if __name__ == '__main__':
    socketio.run(app, debug=True)
