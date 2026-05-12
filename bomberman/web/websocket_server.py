"""
WebSocket Server for Real-time Game Updates
Broadcasts game state to connected web clients
"""
from flask import Flask, render_template
from flask_socketio import SocketIO, emit
import sys
import os
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from bomberman.core.engine import GameEngine
from bomberman.agents.llm_agent import LLMAgent
from bomberman.orchestrator import GameOrchestrator
from bomberman.config import SERVER_HOST, SERVER_PORT

app = Flask(__name__,
            template_folder='templates',
            static_folder='static')
app.config['SECRET_KEY'] = 'bomberman-secret-key'
socketio = SocketIO(app, cors_allowed_origins="*")

# Global state
game_engine = None
orchestrator = None
game_thread = None
game_running = False
game_paused = False
speed_multiplier = 1.0


@app.route('/')
def index():
    """Main game view."""
    return render_template('index.html')


@socketio.on('connect')
def handle_connect():
    """Client connected."""
    print('Client connected')
    if game_engine:
        emit_game_state()


@socketio.on('disconnect')
def handle_disconnect():
    """Client disconnected."""
    print('Client disconnected')


@socketio.on('start_game')
def handle_start_game(data):
    """Initialize and start new game."""
    global game_engine, orchestrator, game_thread, game_running

    num_players = data.get('num_players', 1)
    board_size = data.get('board_size', 15)
    ai_model = data.get('ai_model', 'gpt-5')

    # Create game engine
    game_engine = GameEngine(num_players, board_size, board_size)

    # Create orchestrator with agents
    orchestrator = GameOrchestrator(server_url=f"http://{SERVER_HOST}:{SERVER_PORT}")
    for player_id in range(1, num_players + 1):
        agent = LLMAgent(player_id=player_id, model=ai_model)
        orchestrator.add_agent(agent)

    # Start game thread
    game_running = True
    game_thread = threading.Thread(target=run_game_loop)
    game_thread.daemon = True
    game_thread.start()

    emit('game_started', {'message': 'Game started!'}, broadcast=True)


@socketio.on('pause_game')
def handle_pause_game(data):
    """Pause/resume game."""
    global game_paused
    game_paused = data.get('paused', False)
    emit('game_paused', {'paused': game_paused}, broadcast=True)


@socketio.on('reset_game')
def handle_reset_game():
    """Reset game."""
    global game_engine, orchestrator, game_running, game_paused

    game_running = False
    game_paused = False
    game_engine = None
    orchestrator = None

    emit('game_reset', {}, broadcast=True)


@socketio.on('set_speed')
def handle_set_speed(data):
    """Adjust game speed."""
    global speed_multiplier
    speed_multiplier = data.get('speed', 1.0)


def emit_game_state():
    """Broadcast current game state to all clients."""
    if not game_engine:
        return

    players_data = {}
    for pid, player in game_engine.players.items():
        players_data[pid] = {
            'score': player.score,
            'position': (player.x, player.y),
            'alive': player.alive,
            'active': False
        }

    socketio.emit('game_state', {
        'game_state': game_engine.get_state_string(),
        'move_count': game_engine.move_count,
        'players': players_data,
        'active_player': None
    })


def run_game_loop():
    """Main game loop running in background thread."""
    global game_running, game_paused, game_engine, orchestrator

    max_moves = 200
    move_delay = 0.15

    while game_running and game_engine.move_count < max_moves:
        if game_paused:
            time.sleep(0.5)
            continue

        # Each agent takes a turn
        for player_id in sorted(orchestrator.agents.keys()):
            if not game_running:
                break

            agent = orchestrator.agents[player_id]

            # Notify thinking
            socketio.emit('agent_thinking', {
                'agent': agent.get_name(),
                'player_id': player_id
            })

            # Get game state
            game_state = game_engine.get_state_string()
            game_info = game_engine.get_game_info(player_id)

            # Agent decides moves
            moves = agent.decide_moves(game_state, game_info)

            # Execute moves
            for move in moves[:10]:  # Limit to 10 moves
                if not game_running or game_paused:
                    break

                # Execute move
                if move == 'bomb':
                    game_engine.place_bomb(player_id)
                else:
                    game_engine.move_player(player_id, move)

                # Emit move event
                socketio.emit('agent_move', {
                    'agent': agent.get_name(),
                    'player_id': player_id,
                    'move': move
                })

                # Update and broadcast state
                emit_game_state()

                # Delay based on speed
                time.sleep(move_delay * speed_multiplier)

    # Game over
    if game_engine:
        final_scores = {pid: p.score for pid, p in game_engine.players.items()}
        winner = max(final_scores, key=final_scores.get)

        socketio.emit('game_over', {
            'message': f'Player {winner} wins with {final_scores[winner]} points!',
            'scores': final_scores
        })

    game_running = False


def start_web_server(host='0.0.0.0', port=5001):
    """Start WebSocket server."""
    print(f"🌐 Web UI Server")
    print(f"   URL: http://{host}:{port}")
    print(f"   Open in browser to view game")
    print("="*50)

    socketio.run(app, host=host, port=port, debug=False, allow_unsafe_werkzeug=True)


if __name__ == '__main__':
    start_web_server()
