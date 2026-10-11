// MUD-LLM viewer: renders frames produced by mudllm/replay.py. No game rules live here.

const $ = (id) => document.getElementById(id);
const BASE_COLORS = ["#4f8cff", "#ff6b6b", "#3ecf8e", "#f5c542", "#b07cff", "#ff9f43",
  "#2ed3d3", "#ff6bd5", "#9ccc65", "#e0e0e0", "#7f8cff", "#ffb3b3", "#64d8a3", "#d4b85a",
  "#c7a6ff", "#ffc48a"];
const COLORS = new Proxy({}, { get: (_, pid) => BASE_COLORS[(+pid - 1) % BASE_COLORS.length] });
const MONSTER_COLORS = ["#e05d5d", "#d9a441", "#5dbb63", "#5d8fe0", "#b05de0", "#e07f5d",
  "#41b8d9", "#e05db0"];
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
    game: $("liveGame").value,
    comms: $("liveComms").value,
    rooms: +$("liveRooms").value,
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
  const dungeon = view.meta.game === "dungeon";
  const quest = view.meta.game === "quest";
  if (quest) drawQuest(frame); else if (dungeon) drawDungeon(frame); else drawBoard(frame);
  renderInfo(frame);
  renderPlayers(frame);
  renderOrders(frame);
  renderMessages(frame);
  const total = view.frames[view.frames.length - 1].tick;
  $("tickLabel").textContent = `tick ${frame.tick} / ${total}`;
  $("stonesLabel").textContent = quest
    ? `score ${(100 * frame.score).toFixed(0)}% · ${Object.keys(frame.quests).length} active quests`
    : dungeon
      ? `${frame.alive} monster${frame.alive === 1 ? "" : "s"} alive${frame.game_over ? " · all slain" : ""}`
      : `${frame.stones} stones${frame.iron ? `, ${frame.iron} iron` : ""} left${frame.game_over ? " · board cleared" : ""}`;
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
      } else if (cell === "I") {
        ctx.fillStyle = "#6f7f99";
        ctx.fillRect(x + 1, y + 1, size - 2, size - 2);
        ctx.strokeStyle = "#a9b7cf"; ctx.lineWidth = Math.max(1, size / 10);
        ctx.strokeRect(x + size * 0.2, y + size * 0.2, size * 0.6, size * 0.6);
      } else if (cell === "T") {
        ctx.fillStyle = "#f5c542";
        ctx.beginPath(); ctx.arc(x + size / 2, y + size / 2, size * 0.28, 0, Math.PI * 2); ctx.fill();
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

  const teamColors = { 1: "#4f8cff", 2: "#ff6b6b" };
  const versus = Object.values(frame.players).some((p) => p.team === 2);
  for (const [pid, p] of Object.entries(frame.players)) {
    const [r, c] = p.pos;
    const cx = c * size + size / 2, cy = r * size + size / 2;
    const onBomb = frame.bombs.some((b) => b.pos[0] === r && b.pos[1] === c);
    const radius = size * (onBomb ? 0.22 : 0.32);
    ctx.globalAlpha = p.downed ? 0.3 : 1;
    ctx.fillStyle = versus ? teamColors[p.team] : COLORS[pid];
    ctx.beginPath(); ctx.arc(cx, cy - (onBomb ? size * 0.2 : 0), radius, 0, Math.PI * 2); ctx.fill();
    if (frame.hits.includes(+pid)) {
      ctx.strokeStyle = "#ff3030"; ctx.lineWidth = 4;
      ctx.beginPath(); ctx.arc(cx, cy, size * 0.45, 0, Math.PI * 2); ctx.stroke();
    }
    if (size >= 14) {
      ctx.fillStyle = "#0b0d12";
      ctx.font = `bold ${Math.floor(radius)}px ui-sans-serif, sans-serif`;
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText(pid, cx, cy - (onBomb ? size * 0.2 : 0) + 1);
    }
    ctx.globalAlpha = 1;
  }
}

function renderInfo(frame) {
  const m = view.meta;
  const rows = [
    ["source", m.source || "-"],
    ["seed", m.seed ?? "-"],
    ["clock", clockLabel(m)],
  ];
  if (m.comms) rows.push(["comms", m.comms]);
  if (m.config && m.game === "quest") {
    rows.push(["world", `${m.world.zones.length} zones, ${m.world.regions.length} regions, ` +
      `${m.config.num_players} players`]);
    if (m.end) rows.push(["score", `${(100 * m.end.score).toFixed(0)}% (${m.end.quests_done}/${m.end.quests_total} quests)`]);
  } else if (m.config && m.game === "dungeon") {
    rows.push(["dungeon", `${m.config.num_rooms} rooms, ${m.config.num_players} players, ` +
      `${Object.keys(frame.monsters).length} monsters × ${m.config.monster_hp} HP, regen ${m.config.regen}/t`]);
  } else if (m.config) {
    rows.push(["board", `${m.config.width}×${m.config.height}, fuse ${m.config.bomb_fuse}, range ${m.config.bomb_range}`]);
  }
  if (m.end && m.game !== "quest") rows.push(["result", `${m.end.cleared ? "cleared" : "not cleared"} in ${m.end.ticks} ticks`]);
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
  const dungeon = view.meta.game === "dungeon";
  const quest = view.meta.game === "quest";
  $("players").innerHTML = Object.entries(frame.players).map(([pid, p]) => {
    const stat = quest
      ? `<span class="agent">${p.cls} · ${view.meta.world.zones[p.zone]}${p.downed ? " · downed" : ""}</span> ${(p.points || 0).toFixed(1)}`
      : dungeon
      ? `<span class="agent">room ${p.room} · mana ${p.mana}</span> ${p.damage}`
      : `${p.score}${p.hits ? ` <span class="hit">· ${p.hits} hit${p.hits > 1 ? "s" : ""}</span>` : ""}`;
    return `<div class="player">
      <span class="swatch" style="background:${COLORS[pid]}"></span>
      <div>P${pid} <span class="agent">${escapeHtml(agents[pid] || "agent not recorded")}</span></div>
      <div class="score">${stat}</div>
    </div>`;
  }).join("");
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
  // scroll the list itself (scrollIntoView would scroll the whole page)
  const list = $("orders");
  const current = list.querySelector(".decision.current");
  if (current) {
    const top = current.offsetTop - list.offsetTop;
    if (top < list.scrollTop || top > list.scrollTop + list.clientHeight - 40) list.scrollTop = top - 8;
  }
}

function renderMessages(frame) {
  const items = [];
  for (const f of view.frames) {
    for (const c of f.channels || []) {
      if (c.ok) items.push({ tick: f.tick, from: c.player, channel: c.channel, to: [], system: true,
                             text: `${c.op}${c.op === "invite" ? "d someone to" : ""} #${c.channel}` });
    }
    for (const m of f.messages || []) items.push({ tick: f.tick, ...m });
  }
  const card = $("messagesCard");
  card.hidden = !items.length && !(view.meta.comms && view.meta.comms !== "none");
  if (!items.length) {
    $("messages").innerHTML = '<div class="muted">No messages yet.</div>';
    return;
  }
  $("messages").innerHTML = items.reverse().map((m) => {
    const cls = m.tick > frame.tick ? "future" : (m.tick === frame.tick ? "current" : "");
    const to = m.system ? "channel" : m.to.length ? `→ ${m.to.map((p) => "P" + p).join(" ")}` : "→ nobody";
    return `<div class="message ${cls}">
      <div class="dhead"><span style="color:${COLORS[m.from]}">P${m.from}</span>
        <span>#${escapeHtml(m.channel)}</span><span>t${m.tick}</span><span>${to}</span></div>
      <div>${escapeHtml(m.text)}</div></div>`;
  }).join("");
}

function drawDungeon(frame) {
  const top = canvas.getBoundingClientRect().top + window.scrollY;
  const size = Math.floor(Math.max(320, Math.min(720, window.innerHeight - top - 90, window.innerWidth - 480)));
  canvas.width = size;
  canvas.height = size;
  ctx.fillStyle = "#0b0d12";
  ctx.fillRect(0, 0, size, size);

  const n = frame.rooms;
  const cx = size / 2, cy = size / 2;
  const ringR = size * 0.25;
  const angle = (r) => -Math.PI / 2 + (2 * Math.PI * r) / n;
  const roomPos = (r) => [cx + ringR * Math.cos(angle(r)), cy + ringR * Math.sin(angle(r))];
  const box = Math.min(size * 0.17, (2 * Math.PI * ringR) / n * 0.78);
  const monsters = Object.entries(frame.monsters);

  // monster arcs outside the ring, one lane per monster so overlaps stay readable
  monsters.forEach(([key, m], i) => {
    const color = m.alive ? MONSTER_COLORS[i % MONSTER_COLORS.length] : "#3a3f4a";
    const lane = ringR + box * 0.68 + (i % 2) * size * 0.03;
    const step = (2 * Math.PI) / n;
    const first = m.rooms[0], span = m.rooms.length;
    const a0 = angle(first) - step * 0.42, a1 = angle(first) + step * (span - 1) + step * 0.42;
    ctx.strokeStyle = color; ctx.lineWidth = size * 0.022; ctx.lineCap = "round";
    ctx.globalAlpha = m.alive ? 0.9 : 0.4;
    ctx.beginPath(); ctx.arc(cx, cy, lane, a0, a1); ctx.stroke();
    ctx.globalAlpha = 1;
    const mid = (a0 + a1) / 2, lr = Math.min(lane + size * 0.04, size * 0.45);
    ctx.fillStyle = color;
    ctx.font = `bold ${Math.floor(size * 0.026)}px ui-sans-serif, sans-serif`;
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(m.alive ? m.name : `${m.name} ✝`, cx + lr * Math.cos(mid), cy + lr * Math.sin(mid));
  });

  // rooms
  for (let r = 0; r < n; r++) {
    const [x, y] = roomPos(r);
    ctx.fillStyle = "#171b23"; ctx.strokeStyle = "#2c3340"; ctx.lineWidth = 2;
    roundRect(x - box / 2, y - box / 2, box, box, 8); ctx.fill(); ctx.stroke();
    ctx.fillStyle = "#7d8696";
    ctx.font = `${Math.floor(box * 0.15)}px ui-sans-serif, sans-serif`;
    ctx.textAlign = "left"; ctx.textBaseline = "top";
    ctx.fillText(`room ${r}`, x - box / 2 + 6, y - box / 2 + 4);

    // local ice stacks: one snowflake row per monster present
    let row = 0;
    monsters.forEach(([key, m], i) => {
      if (!m.rooms.includes(r) || !m.alive) return;
      const local = Object.values(m.stacks).filter((s) => s[0] === r).length;
      ctx.fillStyle = MONSTER_COLORS[i % MONSTER_COLORS.length];
      ctx.font = `${Math.floor(box * 0.13)}px ui-sans-serif, sans-serif`;
      ctx.textAlign = "right";
      ctx.fillText(local ? "❄".repeat(local) : "·", x + box / 2 - 6, y - box / 2 + 4 + row * box * 0.15);
      row++;
    });

    // players
    const here = Object.entries(frame.players).filter(([, p]) => p.room === r);
    here.forEach(([pid], j) => {
      const cols = 3, pr = box * 0.11;
      const px = x - box / 2 + box * 0.2 + (j % cols) * box * 0.3;
      const py = y + box * 0.08 + Math.floor(j / cols) * box * 0.28;
      ctx.fillStyle = COLORS[pid];
      ctx.beginPath(); ctx.arc(px, py, pr, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = "#0b0d12";
      ctx.font = `bold ${Math.floor(pr * 1.1)}px ui-sans-serif, sans-serif`;
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText(pid, px, py + 1);
    });
  }

  // fires this tick: burst on the room with the damage
  for (const f of frame.fires) {
    const [x, y] = roomPos(f.room);
    const g = ctx.createRadialGradient(x, y, 4, x, y, box * 0.9);
    g.addColorStop(0, "rgba(255,220,150,0.55)"); g.addColorStop(1, "rgba(255,90,30,0)");
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, box * 0.9, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = "#fff";
    ctx.font = `bold ${Math.floor(box * 0.24)}px ui-sans-serif, sans-serif`;
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(`${f.damage}`, x, y - box * 0.62);
    ctx.font = `${Math.floor(box * 0.13)}px ui-sans-serif, sans-serif`;
    ctx.fillText(`P${f.player} · ${f.stacks}❄`, x, y - box * 0.42);
  }

  // centre: HP bars
  const barW = size * 0.34, barH = size * 0.024;
  monsters.forEach(([key, m], i) => {
    const y = cy - (monsters.length * barH * 1.9) / 2 + i * barH * 1.9;
    const color = MONSTER_COLORS[i % MONSTER_COLORS.length];
    ctx.fillStyle = "#1f2430"; ctx.fillRect(cx - barW / 2, y, barW, barH);
    ctx.fillStyle = m.alive ? color : "#3a3f4a";
    ctx.fillRect(cx - barW / 2, y, barW * Math.max(0, m.hp) / m.max_hp, barH);
    ctx.fillStyle = "#d8dde6";
    ctx.font = `${Math.floor(barH * 0.75)}px ui-sans-serif, sans-serif`;
    ctx.textAlign = "left"; ctx.textBaseline = "middle";
    ctx.fillText(`${m.name} ${m.alive ? m.hp : "slain"}`, cx - barW / 2 + 4, y + barH / 2 + 1);
  });
  for (const k of frame.kills) {
    ctx.fillStyle = "#f5c542";
    ctx.font = `bold ${Math.floor(size * 0.04)}px ui-sans-serif, sans-serif`;
    ctx.textAlign = "center";
    ctx.fillText(`${frame.monsters[k.monster].name} slain by P${k.by}!`, cx, cy - size * 0.11);
  }
}

const CLASS_COLORS = { frost: "#5cc8ff", fire: "#ff6b3d", healer: "#7ddc6f", scout: "#f5c542",
  locksmith: "#c79cff" };
const QUEST_ICONS = { ritual: "◆", vault: "▣", gates: "⛩", boss: "☠" };

function drawQuest(frame) {
  const w = view.meta.world;
  const top = canvas.getBoundingClientRect().top + window.scrollY;
  const size = Math.floor(Math.max(320, Math.min(760, window.innerHeight - top - 90, window.innerWidth - 480)));
  canvas.width = size; canvas.height = size;
  ctx.fillStyle = "#0b0d12"; ctx.fillRect(0, 0, size, size);
  const pos = (z) => [w.layout[z][0] * size, w.layout[z][1] * size];
  const r = Math.max(6, Math.min(16, size / Math.sqrt(w.zones.length) / 3.2));

  // region labels at region centroids
  w.regions.forEach((name, ri) => {
    const zs = w.zone_region.map((rr, z) => (rr === ri ? z : -1)).filter((z) => z >= 0);
    const cx = zs.reduce((a, z) => a + pos(z)[0], 0) / zs.length;
    const cy = zs.reduce((a, z) => a + pos(z)[1], 0) / zs.length;
    ctx.fillStyle = "#3a4150"; ctx.font = `${Math.floor(size * 0.018)}px ui-sans-serif, sans-serif`;
    ctx.textAlign = "center"; ctx.fillText(name.replace(/^the /, ""), cx, cy + 3);
  });
  ctx.strokeStyle = "#262c38"; ctx.lineWidth = 1.5;
  for (const [a, b] of w.edges) {
    const [x1, y1] = pos(a), [x2, y2] = pos(b);
    ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
  }
  // gates: dashed links between a quest's gates
  for (const q of Object.values(frame.quests)) {
    if (q.kind !== "gates") continue;
    ctx.setLineDash([4, 4]); ctx.strokeStyle = "#f5c54288";
    ctx.beginPath();
    q.gates.forEach(([z], i) => { const [x, y] = pos(z); if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y); });
    ctx.closePath(); ctx.stroke(); ctx.setLineDash([]);
  }
  for (let z = 0; z < w.zones.length; z++) {
    const [x, y] = pos(z);
    ctx.fillStyle = "#171b23"; ctx.strokeStyle = "#323a48"; ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
  }
  // quests
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  for (const q of Object.values(frame.quests)) {
    const zones = q.kind === "gates" ? q.gates.map((g) => g[0]) : [q.zone];
    for (const z of zones) {
      const [x, y] = pos(z);
      ctx.fillStyle = q.kind === "boss" ? "#e05d5d" : "#f5c542";
      ctx.font = `bold ${Math.floor(r * 1.3)}px ui-sans-serif, sans-serif`;
      ctx.fillText(QUEST_ICONS[q.kind], x, y - r * 1.55);
    }
    if (q.kind === "boss") {
      const [x, y] = pos(q.zone);
      ctx.fillStyle = "#1f2430"; ctx.fillRect(x - r * 1.4, y - r * 2.6, r * 2.8, 4);
      ctx.fillStyle = "#e05d5d"; ctx.fillRect(x - r * 1.4, y - r * 2.6, r * 2.8 * q.hp / q.max_hp, 4);
    }
    if (q.kind === "vault" && q.key_zone !== null && q.key_zone !== undefined) {
      const [x, y] = pos(q.key_zone);
      ctx.fillStyle = "#f5c542"; ctx.font = `${Math.floor(r * 1.1)}px ui-sans-serif, sans-serif`;
      ctx.fillText("⚷", x + r * 1.2, y - r * 1.1);
    }
  }
  // players: class-coloured dots around their zone
  const byZone = {};
  for (const [pid, p] of Object.entries(frame.players)) (byZone[p.zone] ||= []).push([pid, p]);
  for (const [z, ps] of Object.entries(byZone)) {
    const [x, y] = pos(+z);
    ps.forEach(([pid, p], i) => {
      const a = (2 * Math.PI * i) / Math.max(ps.length, 1);
      const rr = ps.length === 1 ? 0 : r * 0.55;
      ctx.fillStyle = CLASS_COLORS[p.cls] || "#ccc";
      ctx.globalAlpha = p.downed ? 0.35 : 1;
      ctx.beginPath(); ctx.arc(x + rr * Math.cos(a), y + rr * Math.sin(a), Math.max(2.5, r * 0.32), 0, Math.PI * 2); ctx.fill();
      ctx.globalAlpha = 1;
    });
  }
  for (const d of frame.done) {
    const q = d.quest;
    ctx.fillStyle = "#7ddc6f"; ctx.font = `bold ${Math.floor(size * 0.024)}px ui-sans-serif, sans-serif`;
    ctx.fillText(`✓ quest ${q} (${d.kind}) +${d.points}`, size / 2, size * 0.04 + 20 * frame.done.indexOf(d));
  }
  // class legend
  ctx.font = `${Math.floor(size * 0.018)}px ui-sans-serif, sans-serif`; ctx.textAlign = "left";
  Object.entries(CLASS_COLORS).forEach(([cls, col], i) => {
    ctx.fillStyle = col; ctx.beginPath(); ctx.arc(14, size - 16 - i * 16, 5, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = "#9aa3b2"; ctx.fillText(cls, 24, size - 15 - i * 16);
  });
}

function roundRect(x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

// ------------------------------------------------------------------ wiring

$("runSelect").addEventListener("change", (e) => loadRun(e.target.value));
$("refreshRuns").addEventListener("click", loadRuns);
$("toggleLive").addEventListener("click", () => { $("livePanel").hidden = !$("livePanel").hidden; });
$("liveStart").addEventListener("click", startLive);
const AGENTS = {
  bomberman: [["greedy", "greedy (scripted, free)"], ["llm-intent", "llm-intent"]],
  dungeon: [["independent", "independent (scripted, free)"], ["oracle", "oracle (scripted, cheats)"],
            ["llm", "llm"]],
};
function syncLiveForm() {
  const game = $("liveGame").value;
  $("livePolicy").innerHTML = AGENTS[game].map(([v, label]) => `<option value="${v}">${label}</option>`).join("");
  $("livePlayers").max = game === "dungeon" ? 64 : 4;
  $("livePlayers").value = game === "dungeon" ? 8 : 1;
  $("liveRoomsLabel").hidden = game !== "dungeon";
}
$("liveGame").addEventListener("change", syncLiveForm);
syncLiveForm();
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
