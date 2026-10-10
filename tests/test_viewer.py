import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from mudllm.games.bomberman import BombermanConfig, BombermanGame
from mudllm.policies.bfs import BFSPolicy
from mudllm.runner import run_solo
from mudllm.viewer.server import make_handler


@pytest.fixture
def server(tmp_path):
    cfg = BombermanConfig()
    (tmp_path / "bench").mkdir()
    run_solo(BombermanGame(cfg, seed=1), BFSPolicy(cfg), max_ticks=60).log.write_jsonl(
        tmp_path / "bench" / "bfs_seed1.jsonl")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(tmp_path, {}))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}", tmp_path
    httpd.shutdown()


def get(url):
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read()) if "json" in r.headers["Content-Type"] else r.read()


def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def test_serves_page_and_assets(server):
    base, _ = server
    assert b"<canvas" in get(base + "/")
    assert b"drawBoard" in get(base + "/static/app.js")


def test_lists_and_loads_runs(server):
    base, _ = server
    runs = get(base + "/api/runs")
    assert [r["path"] for r in runs] == ["bench/bfs_seed1.jsonl"]
    data = get(base + "/api/run?path=bench/bfs_seed1.jsonl")
    assert data["frames"][0]["tick"] == 0 and data["frames"][-1]["tick"] == 60
    assert data["meta"]["agents"] == {"1": "bfs"}


@pytest.mark.parametrize("path", ["../../etc/passwd", "/etc/passwd"])
def test_rejects_paths_outside_runs_dir(server, path):
    base, _ = server
    with pytest.raises(urllib.error.HTTPError) as err:
        get(base + "/api/run?path=" + path)
    assert err.value.code == 404


def test_live_game_streams_frames_and_saves_log(server):
    base, runs_dir = server
    post(base + "/api/live", {"policy": "greedy", "seed": 2, "max_ticks": 40})
    deadline = time.time() + 20
    while time.time() < deadline:
        data = get(base + "/api/live?since=0")
        if not data["running"] and data["total"]:
            break
        time.sleep(0.1)
    assert data["frames"][-1]["tick"] == 40
    assert data["error"] is None
    assert list((runs_dir / "live").glob("*.jsonl"))
