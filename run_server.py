#!/usr/bin/env python3
"""
Start Bomberman Server
Simple server launcher
"""
import sys
import argparse
sys.path.insert(0, 'bomberman')

from bomberman.server.api import start_server
from bomberman.config import NUM_PLAYERS, BOARD_WIDTH, BOARD_HEIGHT, SERVER_HOST, SERVER_PORT


def main():
    parser = argparse.ArgumentParser(description='Start Bomberman Server')
    parser.add_argument('--players', '-p', type=int, default=NUM_PLAYERS,
                        help=f'Number of players (default: {NUM_PLAYERS})')
    parser.add_argument('--width', '-w', type=int, default=BOARD_WIDTH,
                        help=f'Board width (default: {BOARD_WIDTH})')
    parser.add_argument('--height', '-H', type=int, default=BOARD_HEIGHT,
                        help=f'Board height (default: {BOARD_HEIGHT})')
    parser.add_argument('--port', type=int, default=SERVER_PORT,
                        help=f'Server port (default: {SERVER_PORT})')

    args = parser.parse_args()

    start_server(
        num_players=args.players,
        width=args.width,
        height=args.height,
        port=args.port
    )


if __name__ == '__main__':
    main()
