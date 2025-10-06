# Bomberman Multi-Agent Game

Clean, refactored Bomberman with LLM agents and multi-player support.

## Architecture

```
bomberman/
├── config.py              # Game settings
├── core/                  # Game engine
│   ├── game.py           # Board & Player classes
│   └── engine.py         # Game loop & logic
├── server/               # Flask API
│   └── api.py           # REST endpoints
├── agents/              # AI agents
│   ├── base_agent.py   # Abstract agent
│   ├── llm_agent.py    # LLM-based agent
│   └── prompts.py      # Prompt templates
└── orchestrator.py     # Multi-agent coordinator
```

## Quick Start

### 1. Start Server

```bash
# Terminal 1: Start server with default settings (1 player, 15x15)
source MUD-LLM-venv/bin/activate
python run_server.py

# Or with custom settings
python run_server.py --players 4 --width 21 --height 21
```

### 2. Run Agents

```bash
# Terminal 2: Run single agent
source MUD-LLM-venv/bin/activate
python run_agents.py --players 1 --model gpt-5

# Run 4 agents (multi-player)
python run_agents.py --players 4 --model gpt-5-mini --rounds 10
```

## Configuration

Edit `bomberman/config.py` to change:
- Board size
- Number of players
- Bomb mechanics (timer, range, scoring)
- LLM model
- Server settings

## Usage Examples

```bash
# Single player, 100 moves, GPT-5
python run_agents.py --players 1 --max-moves 100 --model gpt-5

# 2 players, 5 rounds, GPT-5-mini
python run_agents.py --players 2 --rounds 5 --model gpt-5-mini

# Custom server port
python run_server.py --port 8000
python run_agents.py --server http://localhost:8000 --players 1
```

## API Endpoints

- `POST /init` - Initialize new game
- `POST /move` - Move player
- `POST /bomb` - Place bomb
- `GET /state` - Get game state
- `GET /state/<player_id>` - Get player-specific state
- `POST /reset` - Reset game
- `GET /health` - Health check

## Adding New Agents

Extend `BaseAgent` class:

```python
from bomberman.agents.base_agent import BaseAgent

class MyAgent(BaseAgent):
    def decide_moves(self, game_state: str, game_info: str) -> List[str]:
        # Your logic here
        return ["up", "right", "bomb", ...]

    def get_name(self) -> str:
        return "MyAgent"
```

## Game Rules

- **Board**: Grid with walls (#), stones (S), and empty spaces ( )
- **Movement**: up/down/left/right or pass
- **Bombs**: Explode after 3 moves in + pattern, range 2
- **Scoring**: +10 per stone destroyed, -50 if hit by explosion
- **Goal**: Maximize score by destroying stones while avoiding explosions
