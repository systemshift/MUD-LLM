"""
Bomberman Game Configuration
Centralized settings for game server and agents
"""

# ============================================================================
# GAME SETTINGS
# ============================================================================

# Board dimensions (must be odd numbers for proper wall placement)
BOARD_WIDTH = 15
BOARD_HEIGHT = 15

# Number of players (1-4 supported)
NUM_PLAYERS = 1

# Player starting positions (row, col) - will use first NUM_PLAYERS positions
PLAYER_STARTING_POSITIONS = [
    (1, 1),          # Player 1: top-left
    (1, 13),         # Player 2: top-right
    (13, 1),         # Player 3: bottom-left
    (13, 13),        # Player 4: bottom-right
]

# ============================================================================
# GAME MECHANICS
# ============================================================================

# Bomb timer (moves until explosion)
BOMB_TIMER = 3

# Bomb explosion range (cells in each direction)
BOMB_RANGE = 2

# Scoring
STONE_DESTROY_POINTS = 10
EXPLOSION_HIT_PENALTY = -50

# Stone generation probability (0.0 - 1.0)
STONE_PROBABILITY = 0.3

# ============================================================================
# SERVER SETTINGS
# ============================================================================

# Flask server configuration
SERVER_HOST = "localhost"
SERVER_PORT = 5000
DEBUG_MODE = True

# ============================================================================
# AGENT SETTINGS
# ============================================================================

# LLM model to use for agents
# Any Responses API model, e.g. "gpt-6-astra", "gpt-6-sol", "gpt-5.5", "gpt-5-mini"
LLM_MODEL = "gpt-6-astra"

# Reasoning effort: "low", "medium", "high", "xhigh", "max" (gpt-6-astra has no "none")
REASONING_EFFORT = "medium"

# Maximum actions per plan (agents may submit fewer)
MOVES_PER_PLAN = 10

# Delay between moves (seconds) - for visualization
MOVE_DELAY = 0.15

# ============================================================================
# COORDINATION / HYPERGRAPH SETTINGS (Future)
# ============================================================================

# Enable chat between agents
ENABLE_CHAT = False

# Chat filtering strategy
# Options: "broadcast", "spatial", "hypergraph"
CHAT_FILTER_MODE = "spatial"

# Spatial filter radius (for spatial mode)
SPATIAL_FILTER_RADIUS = 5

# Maximum chat history to include in agent context
MAX_CHAT_HISTORY = 10
