"""
Game Orchestrator
Manages multiple agents and coordinates their turns
"""
import requests
import time
from typing import List, Dict
from bomberman.agents.base_agent import BaseAgent
from bomberman.config import MOVE_DELAY


class GameOrchestrator:
    """Coordinates multiple agents playing the game."""

    def __init__(self, server_url: str = "http://localhost:5000"):
        self.server_url = server_url
        self.agents: Dict[int, BaseAgent] = {}
        self.running = False

    def add_agent(self, agent: BaseAgent):
        """Add an agent to the game."""
        self.agents[agent.player_id] = agent
        print(f"✅ Added {agent.get_name()}")

    def get_game_state(self, player_id: int = None) -> Dict:
        """Get current game state from server."""
        try:
            if player_id:
                response = requests.get(f"{self.server_url}/state/{player_id}")
            else:
                response = requests.get(f"{self.server_url}/state")

            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"❌ Error getting game state: {e}")

        return {}

    def execute_move(self, player_id: int, move: str) -> bool:
        """Execute a single move for a player."""
        try:
            if move == "bomb":
                response = requests.post(
                    f"{self.server_url}/bomb",
                    json={"player_id": player_id}
                )
            else:
                response = requests.post(
                    f"{self.server_url}/move",
                    json={"player_id": player_id, "direction": move}
                )

            if response.status_code == 200:
                return response.json().get('success', False)

        except Exception as e:
            print(f"❌ Error executing move: {e}")

        return False

    def run_agent_turn(self, agent: BaseAgent) -> int:
        """Run one agent's turn (decide and execute moves). Returns moves executed."""
        # Get current state
        state_data = self.get_game_state(agent.player_id)
        if not state_data:
            return 0

        game_state = state_data.get('game_state', '')
        game_info = state_data.get('game_info', '')

        # Agent decides moves
        print(f"\n{'='*60}")
        print(f"🎮 {agent.get_name()} turn")
        print(f"{'='*60}")
        print(game_state)
        print(game_info)

        moves = agent.decide_moves(game_state, game_info)
        print(f"📋 Planned moves: {moves}")

        # Execute moves sequentially
        executed = 0
        for i, move in enumerate(moves, 1):
            print(f"  ▶️  Move {i}: {move}")
            success = self.execute_move(agent.player_id, move)

            if success:
                executed += 1
                agent.move_count += 1
            else:
                print(f"     ❌ Failed")

            time.sleep(MOVE_DELAY)

        print(f"✅ Executed {executed}/{len(moves)} moves")
        return executed

    def run_single_player(self, agent: BaseAgent, max_moves: int = 100):
        """Run single agent game."""
        self.add_agent(agent)
        self.running = True

        print(f"\n{'='*60}")
        print(f"🚀 Starting Single Player Game")
        print(f"   Agent: {agent.get_name()}")
        print(f"   Max Moves: {max_moves}")
        print(f"{'='*60}\n")

        total_moves = 0

        while self.running and total_moves < max_moves:
            executed = self.run_agent_turn(agent)
            total_moves += executed

            if executed == 0:
                print("⚠️  No moves executed, stopping...")
                break

        # Final state
        final_state = self.get_game_state(agent.player_id)
        print(f"\n{'='*60}")
        print(f"🏁 GAME OVER")
        print(f"{'='*60}")
        if final_state:
            print(final_state.get('game_info', ''))
            player_info = final_state.get('player_info', {})
            print(f"Final Score: {player_info.get('score', 0)}")

    def run_multi_player(self, max_rounds: int = 10):
        """Run multi-player game with all agents taking turns."""
        if len(self.agents) < 2:
            print("❌ Need at least 2 agents for multi-player")
            return

        self.running = True

        print(f"\n{'='*60}")
        print(f"🚀 Starting Multi-Player Game")
        print(f"   Agents: {len(self.agents)}")
        for agent in self.agents.values():
            print(f"      - {agent.get_name()}")
        print(f"   Max Rounds: {max_rounds}")
        print(f"{'='*60}\n")

        for round_num in range(1, max_rounds + 1):
            print(f"\n{'#'*60}")
            print(f"# ROUND {round_num}")
            print(f"{'#'*60}")

            # Each agent takes a turn
            for player_id in sorted(self.agents.keys()):
                agent = self.agents[player_id]
                self.run_agent_turn(agent)

                time.sleep(0.5)  # Brief pause between players

        # Final scores
        final_state = self.get_game_state()
        print(f"\n{'='*60}")
        print(f"🏁 GAME OVER")
        print(f"{'='*60}")
        if final_state:
            print(final_state.get('game_info', ''))
            for player_id, player_info in final_state.get('all_players', {}).items():
                print(f"Player {player_id}: Score {player_info.get('score', 0)}")

    def stop(self):
        """Stop the game."""
        self.running = False
