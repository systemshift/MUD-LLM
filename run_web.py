#!/usr/bin/env python3
"""
Run Bomberman Web UI
Starts web server with live game visualization
"""
import sys
import argparse
sys.path.insert(0, 'bomberman')

from bomberman.web.websocket_server import start_web_server


def main():
    parser = argparse.ArgumentParser(
        description='Start Bomberman Web UI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start web UI on default port (5001)
  python run_web.py

  # Custom port
  python run_web.py --port 8080

  # Custom host (allow external connections)
  python run_web.py --host 0.0.0.0 --port 5001

Then open your browser to http://localhost:5001
        """
    )

    parser.add_argument('--host', type=str, default='0.0.0.0',
                        help='Host address (default: 0.0.0.0)')
    parser.add_argument('--port', '-p', type=int, default=5001,
                        help='Port number (default: 5001)')

    args = parser.parse_args()

    print("🎮 Bomberman Web UI")
    print("="*50)
    print(f"Starting web server...")
    print(f"Open your browser to: http://localhost:{args.port}")
    print("="*50)

    start_web_server(host=args.host, port=args.port)


if __name__ == '__main__':
    main()
