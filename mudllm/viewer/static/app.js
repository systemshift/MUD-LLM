// MUD-LLM viewer: renders frames produced by mudllm/replay.py. No game rules live here.

const $ = (id) => document.getElementById(id);
const COLORS = { 1: "#4f8cff", 2: "#ff6b6b", 3: "#3ecf8e", 4: "#f5c542" };
const TILE = { wall: "#3a4150", wallTop: "#4a5263", stone: "#8b6b4a", stoneLine: "#6e5238", floor: "#151920" };

const view = {
  meta: {},
  frames: [],
  index: 0,
  playing: false,
  timer: null,
  live: false,
  pollTimer: null,
};

const canvas = $("board");
const ctx = canvas.getContext("2d");

// ------------------------------------------------------------------ data loading

async function loadRuns() {
  const runs = await (await fetch("/api/runs")).json();
  const select = $("runSelect");
  const current = select.value;
  select.innerHTML = '<option value="">choose a run…</option>';
  for (const run of runs) {
    const opt = document.createElement("option");
    opt.value = run.path;
    opt.textContent = run.path;
    select.appendChild(opt);
  }
  select.value = current;
}

async function loadRun(path, tick = null) {
  if (!path) return;
  stopLivePolling();
  const data = await (await fetch(`/api/run?path=${encodeURIComponent(path)}`)).json();
  if (data.error) return alert(data.error);
  view.meta = { ...data.meta, source: path };
  view.frames = data.frames;
  view.live = false;
  $("runSelect").value = path;
  history.replaceState(null, "", `?run=${encodeURIComponent(path)}`);
  if (tick === null) {
    setIndex(0);
    setPlaying(true);
  } else {
    setPlaying(false);
    setIndex(view.frames.findIndex((f) => f.tick >= tick));
  }
}

// ------------------------------------------------------------------ live games

async function startLive() {
  const body = {
    policy: $("livePolicy").value,
    model: $("liveModel").value,
    effort: $("liveEffort").value,
    players: +$("livePlayers").value,
    seed: +$("liveSeed").value,
    think_ticks: +$("liveThink").value,
    max_ticks: +$("liveMax").value,
  };
  const res = await fetch("/api/live", { method: "POST", body: JSON.stringify(body) });
  const data = await res.json();
  if (data.error) return setLiveStatus(data.error, "error");
  view.meta = { source: "live" };
  view.frames = [];
  view.live = true;
  $("runSelect").value = "";
  setPlaying(false);
  setLiveStatus("starting…", "running");
  startLivePolling();
}

function startLivePolling() {
  stopLivePolling();
  view.pollTimer = setInterval(pollLive, 250);
}

function stopLivePolling() {
  clearInterval(view.pollTimer);
  view.pollTimer = null;
}

let lastGrowth = Date.now();

async function pollLive() {
  const since = Math.max(0, view.frames.length - 1);  // re-fetch the last frame: it may still grow
  const data = await (await fetch(`/api/live?since=${since}`)).json();
  if (data.meta) view.meta = { ...data.meta, source: "live" };
  if (data.frames && data.frames.length) {
    // the last frame may have grown since we fetched it; replace it
    if (view.frames.length && data.frames[0].tick === view.frames[view.frames.length - 1].tick) {
      view.frames.pop();
    }
    view.frames.push(...data.frames);
    lastGrowth = Date.now();
  }
  if ($("liveFollow").checked && view.frames.length) {
    setIndex(view.frames.length - 1);
  } else {
    updateScrubber();
  }

  if (data.error) {
    setLiveStatus(data.error, "error");
    stopLivePolling();
  } else if (!data.running && data.total) {
    setLiveStatus(view.meta.end?.cleared ? "board cleared" : "finished", "");
    stopLivePolling();
    loadRuns();
  } else if (data.running) {
    const stalled = Date.now() - lastGrowth > 800;
    setLiveStatus(stalled ? "agent thinking…" : `running · tick ${data.total - 1}`, "running");
  }
}

function setLiveStatus(text, kind) {
  const el = $("liveStatus");
  el.textContent = text;
  el.className = kind ? `status-${kind}` : "";
}

// ------------------------------------------------------------------ playback

function setIndex(i) {
  view.index = Math.max(0, Math.min(i, view.frames.length - 1));
  updateScrubber();
  render();
}

function updateScrubber() {
  const scrub = $("scrub");
  scrub.max = Math.max(0, view.frames.length - 1);
  scrub.value = view.index;
}

function setPlaying(on) {
  view.playing = on && view.frames.length > 0;
  $("play").textContent = view.playing ? "⏸" : "▶";
  clearInterval(view.timer);
  if (view.playing) {
    view.timer = setInterval(() => {
      if (view.index >= view.frames.length - 1) {
        if (!view.live) setPlaying(false);
        return;
      }
      setIndex(view.index + 1);
    }, 1000 / +$("speed").value);
  }
}

// ------------------------------------------------------------------ rendering

function render() {
  const frame = view.frames[view.index];
  if (!frame) return;
  drawBoard(frame);
  renderInfo(frame);
  renderPlayers(frame);
  renderOrders(frame);
  const total = view.frames[view.frames.length - 1].tick;
  $("tickLabel").textContent = `tick ${frame.tick} / ${total}`;
  $("stonesLabel").textContent = `${frame.stones} stones left${frame.game_over ? " · board cleared" : ""}`;
}

function drawBoard(frame) {
  const rows = frame.grid.length;
  const cols = frame.grid[0].length;
  // fit the window: leave room for header, timeline, and ticker
  const top = canvas.getBoundingClientRect().top + window.scrollY;
  const maxH = Math.max(240, window.innerHeight - top - 90);
  const maxW = Math.max(240, Math.min(720, window.innerWidth - 480));
  const size = Math.floor(Math.min(maxW / cols, maxH / rows));
  canvas.width = cols * size;
  canvas.height = rows * size;

  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const x = c * size, y = r * size, cell = frame.grid[r][c];
      ctx.fillStyle = TILE.floor;
      ctx.fillRect(x, y, size, size);
      if (cell === "#") {
        ctx.fillStyle = TILE.wall;
        ctx.fillRect(x, y, size, size);
        ctx.fillStyle = TILE.wallTop;
        ctx.fillRect(x + 2, y + 2, size - 4, size * 0.35);
      } else if (cell === "S") {
        ctx.fillStyle = TILE.stone;
        ctx.fillRect(x + 2, y + 2, size - 4, size - 4);
        ctx.strokeStyle = TILE.stoneLine;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(x + 2, y + size / 2); ctx.lineTo(x + size - 2, y + size / 2);
        ctx.moveTo(x + size / 2, y + 2); ctx.lineTo(x + size / 2, y + size / 2);
        ctx.moveTo(x + size / 4, y + size / 2); ctx.lineTo(x + size / 4, y + size - 2);
        ctx.moveTo(x + 3 * size / 4, y + size / 2); ctx.lineTo(x + 3 * size / 4, y + size - 2);
        ctx.stroke();
      }
    }
  }

  for (const blast of frame.blasts) {
    for (const [r, c] of blast.cells) {
      const x = c * size, y = r * size;
      const g = ctx.createRadialGradient(x + size / 2, y + size / 2, 2, x + size / 2, y + size / 2, size * 0.7);
      g.addColorStop(0, "rgba(255,240,180,0.95)");
      g.addColorStop(1, "rgba(255,120,40,0.55)");
      ctx.fillStyle = g;
      ctx.fillRect(x, y, size, size);
    }
  }

  for (const bomb of frame.bombs) {
    const [r, c] = bomb.pos;
    const cx = c * size + size / 2, cy = r * size + size / 2;
    ctx.fillStyle = "#0a0a0a";
    ctx.beginPath(); ctx.arc(cx, cy, size * 0.34, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = COLORS[bomb.owner] || "#888";
    ctx.lineWidth = 2; ctx.stroke();
    ctx.fillStyle = bomb.fuse <= 1 ? "#ff6b6b" : "#f0f0f0";
    ctx.font = `bold ${Math.floor(size * 0.4)}px ui-monospace, monospace`;
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(bomb.fuse, cx, cy + 1);
  }

  for (const [pid, p] of Object.entries(frame.players)) {
    const [r, c] = p.pos;
    const cx = c * size + size / 2, cy = r * size + size / 2;
    const onBomb = frame.bombs.some((b) => b.pos[0] === r && b.pos[1] === c);
    const radius = size * (onBomb ? 0.22 : 0.32);
    ctx.fillStyle = COLORS[pid];
    ctx.beginPath(); ctx.arc(cx, cy - (onBomb ? size * 0.2 : 0), radius, 0, Math.PI * 2); ctx.fill();
    if (frame.hits.includes(+pid)) {
      ctx.strokeStyle = "#ff3030"; ctx.lineWidth = 4;
      ctx.beginPath(); ctx.arc(cx, cy, size * 0.45, 0, Math.PI * 2); ctx.stroke();
    }
    ctx.fillStyle = "#0b0d12";
    ctx.font = `bold ${Math.floor(radius)}px ui-sans-serif, sans-serif`;
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(pid, cx, cy - (onBomb ? size * 0.2 : 0) + 1);
  }
}

function renderInfo(frame) {
  const m = view.meta;
  const rows = [
    ["source", m.source || "-"],
    ["seed", m.seed ?? "-"],
    ["clock", clockLabel(m)],
  ];
  if (m.config) rows.push(["board", `${m.config.width}×${m.config.height}, fuse ${m.config.bomb_fuse}, range ${m.config.bomb_range}`]);
  if (m.end) rows.push(["result", `${m.end.cleared ? "cleared" : "not cleared"} in ${m.end.ticks} ticks`]);
  $("runInfo").innerHTML = "<h2>Run</h2><dl class='kv'>" +
    rows.map(([k, v]) => `<dt>${k}</dt><dd>${escapeHtml(String(v))}</dd>`).join("") + "</dl>";
}

function clockLabel(m) {
  if (m.tick_rate) return `real latency @ ${m.tick_rate} ticks/s`;
  // older logs have no meta event; fall back to what decisions recorded
  const think = m.think_ticks ?? view.frames.flatMap((f) => f.decisions)[0]?.think_ticks ?? 0;
  return think ? `${think} ticks per decision` : "frozen while thinking";
}

function renderPlayers(frame) {
  const agents = view.meta.agents || {};
  $("players").innerHTML = Object.entries(frame.players).map(([pid, p]) => `
    <div class="player">
      <span class="swatch" style="background:${COLORS[pid]}"></span>
      <div>P${pid} <span class="agent">${escapeHtml(agents[pid] || "agent not recorded")}</span></div>
      <div class="score">${p.score}${p.hits ? ` <span class="hit">· ${p.hits} hit${p.hits > 1 ? "s" : ""}</span>` : ""}</div>
    </div>`).join("");
}

function renderOrders(frame) {
  // all decisions in the run, so upcoming ones are visible but dimmed
  const items = [];
  for (const f of view.frames) {
    for (const d of f.decisions) items.push({ tick: f.tick, ...d });
  }
  if (!items.length) {
    $("orders").innerHTML = '<div class="muted">No orders in this run (primitive-action agents plan keypresses).</div>';
    return;
  }
  const html = items.reverse().map((d) => {
    const lands = d.tick + (d.think_ticks || 0);
    const cls = d.tick > frame.tick ? "future" : (frame.tick >= d.tick && frame.tick <= lands + 2 ? "current" : "");
    const think = d.think_ticks ? ` · thinks ${d.think_ticks}t, lands t${lands}` : "";
    const orders = (d.orders || []).map((o) => {
      const [what, ...why] = o.split(" - ");
      return `<li>${escapeHtml(what)}${why.length ? ` <span class="why">${escapeHtml(why.join(" - "))}</span>` : ""}</li>`;
    }).join("");
    return `<div class="decision ${cls}">
      <div class="dhead"><span style="color:${COLORS[d.player]}">P${d.player}</span><span>t${d.tick}${think}</span></div>
      <ol>${orders}</ol></div>`;
  }).join("");
  $("orders").innerHTML = html;
  const current = $("orders").querySelector(".decision.current");
  if (current) current.scrollIntoView({ block: "nearest" });
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

// ------------------------------------------------------------------ wiring

$("runSelect").addEventListener("change", (e) => loadRun(e.target.value));
$("refreshRuns").addEventListener("click", loadRuns);
$("toggleLive").addEventListener("click", () => { $("livePanel").hidden = !$("livePanel").hidden; });
$("liveStart").addEventListener("click", startLive);
$("liveStop").addEventListener("click", () => fetch("/api/live/stop", { method: "POST" }));
$("play").addEventListener("click", () => setPlaying(!view.playing));
$("prev").addEventListener("click", () => { setPlaying(false); setIndex(view.index - 1); });
$("next").addEventListener("click", () => { setPlaying(false); setIndex(view.index + 1); });
$("scrub").addEventListener("input", (e) => { setPlaying(false); $("liveFollow").checked = false; setIndex(+e.target.value); });
$("speed").addEventListener("change", () => setPlaying(view.playing));
window.addEventListener("resize", render);
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
  if (e.key === " ") { e.preventDefault(); setPlaying(!view.playing); }
  if (e.key === "ArrowLeft") { setPlaying(false); setIndex(view.index - 1); }
  if (e.key === "ArrowRight") { setPlaying(false); setIndex(view.index + 1); }
});

// ?run=path[&tick=N] opens a replay directly, e.g. for sharing a moment
// otherwise reattach to a live game that is already running (e.g. after a reload)
loadRuns().then(async () => {
  const params = new URLSearchParams(location.search);
  if (params.get("run")) return loadRun(params.get("run"), params.has("tick") ? +params.get("tick") : null);
  const live = await (await fetch("/api/live?since=0")).json();
  if (live.running) {
    view.live = true;
    view.meta = { source: "live" };
    $("livePanel").hidden = false;
    startLivePolling();
  }
});
