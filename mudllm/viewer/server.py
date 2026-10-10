"""
Viewer server (stdlib only).

  GET  /                    the viewer page
  GET  /api/runs            event logs under the runs directory
  GET  /api/run?path=...    {meta, frames} for one log
  POST /api/live            start a live game {game, policy, comms, model, effort, seed,
                            players, rooms, think_ticks, max_ticks}
  GET  /api/live?since=N    {meta, frames[N:], total, running, error}
  POST /api/live/stop       stop the live game
"""

import json
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ..comms import make_router
from ..games.bomberman import BombermanConfig, BombermanGame
from ..loop import Clock, run_game
from ..replay import Replayer, build_frames
from ..sim import EventLog

STATIC = Path(__file__).parent / "static"
CONTENT_TYPES = {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}


class LiveGame:
    def __init__(self, settings: dict, runs_dir: Path):
        self.settings = settings
        self.runs_dir = runs_dir
        self.log = EventLog()
        self.replayer = Replayer()
        self.lock = threading.Lock()
        self.stop_flag = threading.Event()
        self.running = True
        self.error: str | None = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _agents(self, config, game):
        s = self.settings
        agents = []
        for pid in range(1, config.num_players + 1):
            if s["policy"] == "independent":
                from ..agents.dungeon_scripted import IndependentAgent
                agents.append(IndependentAgent(pid, config))
            elif s["policy"] == "oracle":
                from ..agents.dungeon_scripted import OracleAgent
                agents.append(OracleAgent(pid, game))
            elif s["policy"] == "llm":
                from ..agents.llm_dungeon import LLMDungeonAgent
                from ..agents.providers.openai import OpenAIProvider
                provider = OpenAIProvider(s["model"], s["effort"])
                agents.append(LLMDungeonAgent(pid, config, provider, think_ticks=s["think_ticks"]))
            elif s["policy"] == "greedy":
                from ..agents.greedy import GreedyIntentAgent
                agents.append(GreedyIntentAgent(pid, config))
            else:
                from ..agents.llm_intent import LLMIntentAgent
                from ..agents.providers.openai import OpenAIProvider
                provider = OpenAIProvider(s["model"], s["effort"])
                agents.append(LLMIntentAgent(pid, config, provider, think_ticks=s["think_ticks"]))
        return agents

    def _run(self):
        s = self.settings
        try:
            if s["game"] == "dungeon":
                from ..games.dungeon import DungeonConfig, DungeonGame
                config = DungeonConfig(num_rooms=s["rooms"], num_players=s["players"])
                game = DungeonGame(config, seed=s["seed"])
            else:
                config = BombermanConfig(num_players=min(4, s["players"]))
                game = BombermanGame(config, seed=s["seed"])
            # Scripted agents decide instantly; pace them so the game is watchable
            pace = s["policy"] in ("greedy", "independent", "oracle")

            def on_tick(*_):
                if pace:
                    time.sleep(0.1)

            run_game(game, self._agents(config, game), Clock(think_ticks=s["think_ticks"]),
                     max_ticks=s["max_ticks"], log=self.log, on_tick=on_tick,
                     should_stop=self.stop_flag.is_set, comms=make_router(s["comms"]))
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            traceback.print_exc()
        finally:
            self.running = False
            if len(self.log.events) > 2:
                out = self.runs_dir / "live"
                out.mkdir(parents=True, exist_ok=True)
                self.log.write_jsonl(out / f"{time.strftime('%Y%m%d-%H%M%S')}_{s['policy']}.jsonl")

    def frames_since(self, n: int) -> dict:
        with self.lock:
            self.replayer.feed(list(self.log.events))
            frames = self.replayer.frames
            return {"meta": self.replayer.meta, "frames": frames[n:], "total": len(frames),
                    "running": self.running, "error": self.error}


def make_handler(runs_dir: Path, state: dict):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # keep the terminal quiet
            pass

        def handle_one_request(self):
            try:
                super().handle_one_request()
            except (BrokenPipeError, ConnectionResetError):
                pass  # browser navigated away mid-response

        def _json(self, obj, status: int = 200):
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _static(self, name: str):
            path = (STATIC / name).resolve()
            if not path.is_relative_to(STATIC.resolve()) or not path.is_file():
                return self._json({"error": "not found"}, 404)
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPES.get(path.suffix, "text/plain"))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlparse(self.path)
            query = parse_qs(url.query)
            if url.path == "/":
                return self._static("index.html")
            if url.path.startswith("/static/"):
                return self._static(url.path.removeprefix("/static/"))
            if url.path == "/api/runs":
                files = sorted(runs_dir.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime,
                               reverse=True) if runs_dir.exists() else []
                return self._json([{"path": str(p.relative_to(runs_dir)),
                                    "mtime": p.stat().st_mtime} for p in files])
            if url.path == "/api/run":
                rel = query.get("path", [""])[0]
                path = (runs_dir / rel).resolve()
                if not path.is_relative_to(runs_dir.resolve()) or not path.is_file():
                    return self._json({"error": "run not found"}, 404)
                meta, frames = build_frames(EventLog.read_jsonl(path).events)
                return self._json({"meta": meta, "frames": frames})
            if url.path == "/api/live":
                live = state.get("live")
                if not live:
                    return self._json({"frames": [], "total": 0, "running": False})
                return self._json(live.frames_since(int(query.get("since", ["0"])[0])))
            self._json({"error": "not found"}, 404)

        def do_POST(self):
            url = urlparse(self.path)
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            if url.path == "/api/live":
                live = state.get("live")
                if live and live.running:
                    return self._json({"error": "a live game is already running"}, 409)
                settings = {
                    "policy": body.get("policy", "greedy"),
                    "model": body.get("model", "gpt-6-astra"),
                    "effort": body.get("effort", "medium"),
                    "seed": int(body.get("seed", 1)),
                    "game": body.get("game", "bomberman"),
                    "comms": body.get("comms", "none"),
                    "rooms": max(3, min(64, int(body.get("rooms", 4)))),
                    "players": max(1, min(64, int(body.get("players", 1)))),
                    "think_ticks": max(0, int(body.get("think_ticks", 0))),
                    "max_ticks": max(10, min(2000, int(body.get("max_ticks", 400)))),
                }
                state["live"] = LiveGame(settings, runs_dir)
                return self._json({"started": settings})
            if url.path == "/api/live/stop":
                live = state.get("live")
                if live:
                    live.stop_flag.set()
                return self._json({"stopped": bool(live)})
            self._json({"error": "not found"}, 404)

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8765, runs_dir: str = "runs"):
    server = ThreadingHTTPServer((host, port), make_handler(Path(runs_dir), {}))
    print(f"mudllm viewer: http://{host}:{port}  (runs from {Path(runs_dir).resolve()})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
