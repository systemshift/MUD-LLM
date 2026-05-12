#!/usr/bin/env python3
"""
Run Bomberman Agents
Launch N agents to play the game
"""
import sys
import argparse
sys.path.insert(0, 'bomberman')

from bomberman.agents.llm_agent import LLMAgent
from bomberman.orchestrator import GameOrchestrator
from bomberman.config import LLM_MODEL, SERVER_HOST, SERVER_PORT


def main():
    parser = argparse.ArgumentParser(
        description='Run Bomberman Agents',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single player with GPT-5
  python run_agents.py --players 1 --model gpt-5

  # 4 players with GPT-5-mini
  python run_agents.py --players 4 --model gpt-5-mini --rounds 5

  # Custom max moves for single player
  python run_agents.py --players 1 --max-moves 200
        """
    )

    parser.add_argument('--players', '-p', type=int, default=1,
                        help='Number of AI players (default: 1)')
    parser.add_argument('--model', '-m', type=str, default=LLM_MODEL,
                        choices=['gpt-5.5', 'gpt-5', 'gpt-5-mini', 'gpt-5-nano', 'o4-mini', 'gpt-4o-mini'],
                        help=f'LLM model to use (default: {LLM_MODEL})')
    parser.add_argument('--server', '-s', type=str,
                        default=f"http://{SERVER_HOST}:{SERVER_PORT}",
                        help='Server URL')
    parser.add_argument('--max-moves', type=int, default=100,
                        help='Max moves for single player (default: 100)')
    parser.add_argument('--rounds', '-r', type=int, default=10,
                        help='Max rounds for multi-player (default: 10)')

    args = parser.parse_args()

    # Create orchestrator
    orchestrator = GameOrchestrator(server_url=args.server)

    # Create agents
    print(f"🤖 Creating {args.players} agent(s) using {args.model}...")
    for player_id in range(1, args.players + 1):
        agent = LLMAgent(player_id=player_id, model=args.model, server_url=args.server)
        orchestrator.add_agent(agent)

    # Run game
    if args.players == 1:
        agent = list(orchestrator.agents.values())[0]
        orchestrator.run_single_player(agent, max_moves=args.max_moves)
    else:
        orchestrator.run_multi_player(max_rounds=args.rounds)


if __name__ == '__main__':
    main()
