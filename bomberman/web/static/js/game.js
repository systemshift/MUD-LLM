// Bomberman Game Board Renderer
class GameRenderer {
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        this.ctx = this.canvas.getContext('2d');
        this.cellSize = 50;
        this.boardSize = 15;
        this.gameState = null;
        this.animations = [];

        // Colors
        this.colors = {
            wall: '#34495e',
            stone: '#95a5a6',
            empty: '#ecf0f1',
            bomb: '#e74c3c',
            player1: '#3b82f6',
            player2: '#ef4444',
            player3: '#10b981',
            player4: '#f59e0b',
            explosion: '#ff6b6b'
        };
    }

    resize(boardSize) {
        this.boardSize = boardSize;
        const size = boardSize * this.cellSize;
        this.canvas.width = size;
        this.canvas.height = size;
    }

    drawCell(x, y, type, label = '') {
        const px = x * this.cellSize;
        const py = y * this.cellSize;

        // Fill cell
        this.ctx.fillStyle = this.colors[type] || this.colors.empty;
        this.ctx.fillRect(px, py, this.cellSize, this.cellSize);

        // Border
        this.ctx.strokeStyle = '#bdc3c7';
        this.ctx.lineWidth = 1;
        this.ctx.strokeRect(px, py, this.cellSize, this.cellSize);

        // Draw symbol/text
        if (label) {
            this.ctx.fillStyle = type === 'wall' || type === 'stone' ? 'white' : 'black';
            this.ctx.font = 'bold 24px Arial';
            this.ctx.textAlign = 'center';
            this.ctx.textBaseline = 'middle';
            this.ctx.fillText(label, px + this.cellSize / 2, py + this.cellSize / 2);
        }
    }

    drawBoard(gameStateString) {
        const lines = gameStateString.trim().split('\n');
        this.boardSize = lines.length;
        this.resize(this.boardSize);

        // Clear canvas
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

        // Draw each cell
        for (let y = 0; y < lines.length; y++) {
            for (let x = 0; x < lines[y].length; x++) {
                const char = lines[y][x];
                let type = 'empty';
                let label = '';

                switch (char) {
                    case '#':
                        type = 'wall';
                        break;
                    case 'S':
                        type = 'stone';
                        label = '📦';
                        break;
                    case 'B':
                        type = 'bomb';
                        label = '💣';
                        break;
                    case 'P':
                    case '1':
                    case '2':
                    case '3':
                    case '4':
                        const playerNum = char === 'P' ? 1 : parseInt(char);
                        type = `player${playerNum}`;
                        label = char === 'P' ? '🤖' : `${char}`;
                        break;
                }

                this.drawCell(x, y, type, label);
            }
        }
    }

    drawExplosion(x, y) {
        const px = x * this.cellSize;
        const py = y * this.cellSize;

        this.ctx.fillStyle = 'rgba(255, 107, 107, 0.7)';
        this.ctx.fillRect(px, py, this.cellSize, this.cellSize);

        this.ctx.fillStyle = 'white';
        this.ctx.font = 'bold 30px Arial';
        this.ctx.textAlign = 'center';
        this.ctx.textBaseline = 'middle';
        this.ctx.fillText('💥', px + this.cellSize / 2, py + this.cellSize / 2);
    }
}

// Game Controller
class GameController {
    constructor() {
        this.renderer = new GameRenderer('gameCanvas');
        this.socket = io();
        this.isRunning = false;
        this.isPaused = false;
        this.players = {};

        this.setupSocketListeners();
        this.setupUI();
    }

    setupSocketListeners() {
        this.socket.on('connect', () => {
            console.log('Connected to server');
            this.addLog('Connected to game server', 'info');
        });

        this.socket.on('game_state', (data) => {
            this.updateGameState(data);
        });

        this.socket.on('agent_thinking', (data) => {
            this.addLog(`${data.agent} is thinking...`, 'thinking');
        });

        this.socket.on('agent_move', (data) => {
            this.addLog(`${data.agent}: ${data.move}`, 'move');
        });

        this.socket.on('explosion', (data) => {
            this.handleExplosion(data);
        });

        this.socket.on('game_over', (data) => {
            this.handleGameOver(data);
        });
    }

    setupUI() {
        document.getElementById('startBtn').addEventListener('click', () => this.startGame());
        document.getElementById('pauseBtn').addEventListener('click', () => this.togglePause());
        document.getElementById('resetBtn').addEventListener('click', () => this.resetGame());
        document.getElementById('speedControl').addEventListener('change', (e) => {
            this.socket.emit('set_speed', { speed: parseFloat(e.target.value) });
        });
    }

    startGame() {
        const numPlayers = parseInt(document.getElementById('numPlayers').value);
        const boardSize = parseInt(document.getElementById('boardSize').value);
        const aiModel = document.getElementById('aiModel').value;

        this.socket.emit('start_game', {
            num_players: numPlayers,
            board_size: boardSize,
            ai_model: aiModel
        });

        this.isRunning = true;
        document.getElementById('startBtn').disabled = true;
        document.getElementById('pauseBtn').disabled = false;
        this.addLog(`Starting game: ${numPlayers} players, ${boardSize}x${boardSize} board`, 'info');
    }

    togglePause() {
        this.isPaused = !this.isPaused;
        this.socket.emit('pause_game', { paused: this.isPaused });
        document.getElementById('pauseBtn').textContent = this.isPaused ? 'Resume' : 'Pause';
    }

    resetGame() {
        this.socket.emit('reset_game');
        this.isRunning = false;
        this.isPaused = false;
        document.getElementById('startBtn').disabled = false;
        document.getElementById('pauseBtn').disabled = true;
        document.getElementById('pauseBtn').textContent = 'Pause';
        this.clearLogs();
        this.addLog('Game reset', 'info');
    }

    updateGameState(data) {
        // Draw board
        if (data.game_state) {
            this.renderer.drawBoard(data.game_state);
        }

        // Update status
        document.getElementById('moveCount').textContent = `Move: ${data.move_count || 0}`;
        document.getElementById('activePlayer').textContent = data.active_player || 'Waiting...';

        // Update players list
        if (data.players) {
            this.updatePlayersList(data.players);
        }
    }

    updatePlayersList(players) {
        const container = document.getElementById('playersList');
        container.innerHTML = '';

        Object.entries(players).forEach(([id, player]) => {
            const card = document.createElement('div');
            card.className = `player-card player-${id}`;
            if (player.active) card.classList.add('active');

            card.innerHTML = `
                <div class="player-info">
                    <div class="player-name">Player ${id}</div>
                    <div class="player-stats">
                        Score: ${player.score} |
                        Position: (${player.position[0]}, ${player.position[1]})
                    </div>
                </div>
            `;

            container.appendChild(card);
        });
    }

    handleExplosion(data) {
        data.positions.forEach(pos => {
            this.renderer.drawExplosion(pos[0], pos[1]);
        });
        this.addLog(`💥 Explosion at (${data.positions[0][0]}, ${data.positions[0][1]})`, 'bomb');
    }

    handleGameOver(data) {
        this.isRunning = false;
        document.getElementById('startBtn').disabled = false;
        document.getElementById('pauseBtn').disabled = true;
        this.addLog(`🏁 Game Over! ${data.message}`, 'info');
    }

    addLog(message, type = 'info') {
        const container = document.getElementById('activityLog');
        const entry = document.createElement('div');
        entry.className = `log-entry ${type}`;

        const time = new Date().toLocaleTimeString();
        entry.textContent = `[${time}] ${message}`;

        container.insertBefore(entry, container.firstChild);

        // Keep only last 50 entries
        while (container.children.length > 50) {
            container.removeChild(container.lastChild);
        }
    }

    clearLogs() {
        document.getElementById('activityLog').innerHTML = '';
    }
}

// Initialize when page loads
document.addEventListener('DOMContentLoaded', () => {
    window.gameController = new GameController();
});
