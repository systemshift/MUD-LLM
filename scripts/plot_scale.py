#!/usr/bin/env python3
"""
Render a scaling experiment's results.jsonl as a self-contained HTML report:
small multiples over team size (one y-axis each), hover tooltips, data table,
light/dark mode.

  python scripts/plot_scale.py runs/scale/results.jsonl runs/scale/report.html
"""

import html
import json
import math
import sys
from pathlib import Path

MODES = [  # entity -> color slot; fixed, never by rank
    ("hypergraph", "var(--series-1)", ""),
    ("broadcast", "var(--series-2)", ""),
    ("vector", "var(--series-3)", ""),
    ("none", "var(--baseline)", "6 5"),  # neutral dashed baseline (secondary encoding)
]
LABELS = {"hypergraph": "Hypergraph", "broadcast": "Broadcast", "vector": "Vector",
          "none": "No comms"}

PANELS = [
    ("kill_pct", "Monsters killed", "%", lambda v: f"{v:.0f}%"),
    ("ticks", "Ticks to finish (lower is better)", "ticks", lambda v: f"{v:.0f}"),
    ("inbox_per_agent", "Messages received per agent", "msgs", lambda v: f"{v:.0f}"),
    ("cost_per_agent", "Cost per agent", "$", lambda v: f"${v:.3f}"),
]

W, H = 380, 250
M = {"l": 56, "r": 92, "t": 34, "b": 40}


def load(path: str) -> dict:
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    rows = [r for r in rows if r.get("policy", "llm") == "llm"]
    data: dict[str, dict[int, list[dict]]] = {}
    for r in rows:
        r["kill_pct"] = 100 * r["kill_fraction"]
        r["cost_per_agent"] = r["cost_usd"] / r["size"]
        data.setdefault(r["comms"], {}).setdefault(r["size"], []).append(r)
    return data


def mean(xs):
    return sum(xs) / len(xs)


def nice_max(v: float) -> float:
    if v <= 0:
        return 1
    mag = 10 ** math.floor(math.log10(v))
    for step in (1, 2, 2.5, 5, 10):
        if v <= step * mag:
            return step * mag
    return 10 * mag


def panel(key, title, unit, fmt, data, sizes, max_ticks) -> str:
    pw, ph = W - M["l"] - M["r"], H - M["t"] - M["b"]
    values = [mean([r[key] for r in rs]) for m in data.values() for rs in m.values()]
    ymax = 100 if key == "kill_pct" else nice_max(max(values + [max_ticks if key == "ticks" else 0]))
    lo, hi = math.log2(min(sizes)), math.log2(max(sizes))

    def x(n):
        return M["l"] + (0 if hi == lo else (math.log2(n) - lo) / (hi - lo) * pw)

    def y(v):
        return M["t"] + ph - v / ymax * ph

    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{html.escape(title)} by team size">',
           f'<text x="{M["l"]}" y="18" class="ptitle">{html.escape(title)}</text>']
    for i in range(5):  # recessive grid
        v = ymax * i / 4
        out.append(f'<line x1="{M["l"]}" x2="{M["l"] + pw}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/>')
        out.append(f'<text x="{M["l"] - 8}" y="{y(v) + 4:.1f}" class="tick" text-anchor="end">'
                   f'{html.escape(fmt(v))}</text>')
    for n in sizes:
        out.append(f'<text x="{x(n):.1f}" y="{M["t"] + ph + 18}" class="tick" '
                   f'text-anchor="middle">{n}</text>')
    out.append(f'<text x="{M["l"] + pw / 2}" y="{H - 4}" class="axis" text-anchor="middle">'
               f'team size (agents)</text>')
    if key == "ticks":
        out.append(f'<line x1="{M["l"]}" x2="{M["l"] + pw}" y1="{y(max_ticks):.1f}" '
                   f'y2="{y(max_ticks):.1f}" class="limit"/>')
        out.append(f'<text x="{M["l"] + pw}" y="{y(max_ticks) + 13:.1f}" class="tick" '
                   f'text-anchor="end">time limit</text>')

    ends = []
    for mode, color, dash in MODES:
        if mode not in data:
            continue
        pts = [(n, mean([r[key] for r in data[mode][n]]), data[mode][n])
               for n in sizes if n in data[mode]]
        if not pts:
            continue
        d = " ".join(f"{'M' if i == 0 else 'L'}{x(n):.1f},{y(v):.1f}" for i, (n, v, _) in enumerate(pts))
        out.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2" '
                   f'stroke-dasharray="{dash}" stroke-linejoin="round"/>')
        for n, v, rs in pts:
            seeds = ", ".join(fmt(r[key]) for r in rs)
            tip = f"{LABELS[mode]} · {n} agents: {fmt(v)} (seeds: {seeds})"
            out.append(f'<circle cx="{x(n):.1f}" cy="{y(v):.1f}" r="4.5" fill="{color}" '
                       f'class="pt" data-tip="{html.escape(tip)}"/>')
        ends.append([y(pts[-1][1]), mode, color, x(pts[-1][0])])

    ends.sort()  # direct labels at line ends, nudged apart to avoid collisions
    for i in range(1, len(ends)):
        ends[i][0] = max(ends[i][0], ends[i - 1][0] + 13)
    for ly, mode, _color, lx in ends:
        out.append(f'<text x="{lx + 9:.1f}" y="{ly + 4:.1f}" class="dlabel">{LABELS[mode]}</text>')
    out.append("</svg>")
    return "\n".join(out)


def table(data, sizes) -> str:
    head = ("<tr><th>Agents</th><th>Comms</th><th>Runs</th><th>Killed</th><th>Ticks</th>"
            "<th>Stacks/fire</th><th>Wasted fires</th><th>Msgs recv/agent</th>"
            "<th>Tokens/agent</th><th>$/run</th></tr>")
    rows = []
    for n in sizes:
        for mode, _, _ in MODES:
            rs = data.get(mode, {}).get(n)
            if not rs:
                continue
            rows.append(
                f"<tr><td>{n}</td><td>{LABELS[mode]}</td><td>{len(rs)}</td>"
                f"<td>{mean([r['kill_pct'] for r in rs]):.0f}%</td>"
                f"<td>{mean([r['ticks'] for r in rs]):.0f}</td>"
                f"<td>{mean([r['avg_stacks'] for r in rs]):.2f}</td>"
                f"<td>{mean([r['wasted_fires'] for r in rs]):.0f}</td>"
                f"<td>{mean([r['inbox_per_agent'] for r in rs]):.0f}</td>"
                f"<td>{mean([r['tokens_per_agent'] for r in rs]):,.0f}</td>"
                f"<td>${mean([r['cost_usd'] for r in rs]):.2f}</td></tr>")
    return f"<table>{head}{''.join(rows)}</table>"


def render(results: str, out: str):
    data = load(results)
    sizes = sorted({n for m in data.values() for n in m})
    any_row = next(r for m in data.values() for rs in m.values() for r in rs)
    max_ticks = any_row["max_ticks"]
    model = any_row.get("model") or ""
    seeds = max(len(rs) for m in data.values() for rs in m.values())
    total = sum(r["cost_usd"] for m in data.values() for rs in m.values() for r in rs)
    legend = "".join(
        f'<span class="key"><svg width="26" height="10"><line x1="1" x2="25" y1="5" y2="5" '
        f'stroke="{c}" stroke-width="2" stroke-dasharray="{d}"/></svg>{LABELS[m]}</span>'
        for m, c, d in MODES if m in data)
    panels = "".join(f'<div class="panel">{panel(k, t, u, f, data, sizes, max_ticks)}</div>'
                     for k, t, u, f in PANELS)
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>MUD-LLM scaling experiment</title>
<style>
.viz-root {{ color-scheme: light; --surface-1:#fcfcfb; --text-primary:#0b0b0b; --text-secondary:#52514e;
  --grid:#e6e5e1; --series-1:#2a78d6; --series-2:#eb6834; --series-3:#1baf7a; --baseline:#8a8984; }}
@media (prefers-color-scheme: dark) {{ :root:where(:not([data-theme="light"])) .viz-root {{ color-scheme: dark;
  --surface-1:#1a1a19; --text-primary:#f0efec; --text-secondary:#c3c2b7; --grid:#2e2e2b;
  --series-1:#3987e5; --series-2:#d95926; --series-3:#199e70; --baseline:#8f8e88; }} }}
:root[data-theme="dark"] .viz-root {{ color-scheme: dark; --surface-1:#1a1a19; --text-primary:#f0efec;
  --text-secondary:#c3c2b7; --grid:#2e2e2b; --series-1:#3987e5; --series-2:#d95926; --series-3:#199e70;
  --baseline:#8f8e88; }}
body {{ margin:0; }}
.viz-root {{ background:var(--surface-1); color:var(--text-primary); min-height:100vh;
  font:14px/1.45 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; padding:24px 28px; }}
h1 {{ font-size:20px; margin:0 0 4px; }} .sub {{ color:var(--text-secondary); margin:0 0 14px; }}
.legend {{ display:flex; gap:18px; margin:0 0 10px; color:var(--text-secondary); }}
.key {{ display:inline-flex; align-items:center; gap:6px; white-space:nowrap; }}
.grid-wrap {{ display:grid; grid-template-columns:repeat(2, minmax(320px, 1fr)); gap:10px 24px; max-width:900px; }}
svg {{ width:100%; height:auto; overflow:visible; }}
.ptitle {{ font-size:13px; font-weight:600; fill:var(--text-primary); }}
.tick {{ font-size:11px; fill:var(--text-secondary); font-variant-numeric:tabular-nums; }}
.axis {{ font-size:11px; fill:var(--text-secondary); }}
.dlabel {{ font-size:11px; fill:var(--text-primary); }}
.grid {{ stroke:var(--grid); stroke-width:1; }}
.limit {{ stroke:var(--text-secondary); stroke-width:1; stroke-dasharray:2 3; }}
.pt {{ stroke:var(--surface-1); stroke-width:2; cursor:default; }}
.pt:hover {{ r:6.5; }}
#tip {{ position:fixed; pointer-events:none; background:var(--text-primary); color:var(--surface-1);
  padding:5px 8px; border-radius:6px; font-size:12px; display:none; max-width:320px; }}
details {{ margin-top:18px; max-width:900px; }} summary {{ cursor:pointer; color:var(--text-secondary); }}
table {{ border-collapse:collapse; margin-top:8px; font-variant-numeric:tabular-nums; font-size:13px; }}
th, td {{ padding:4px 10px; text-align:right; border-bottom:1px solid var(--grid); }}
th:nth-child(2), td:nth-child(2) {{ text-align:left; }}
</style></head>
<body><div class="viz-root">
<h1>Does communication help large agent teams, and do hyperedges help more?</h1>
<p class="sub">Dungeon coordination game, {html.escape(model)} agents, team sizes {", ".join(map(str, sizes))};
mean of up to {seeds} seeds per point; hover a point for per-seed values. Total spend ${total:.2f}.</p>
<div class="legend">{legend}</div>
<div class="grid-wrap">{panels}</div>
<details open><summary>Data table</summary>{table(data, sizes)}</details>
<div id="tip"></div>
</div>
<script>
const tip = document.getElementById("tip");
document.querySelectorAll(".pt").forEach((el) => {{
  el.addEventListener("mousemove", (e) => {{
    tip.textContent = el.dataset.tip; tip.style.display = "block";
    tip.style.left = (e.clientX + 14) + "px"; tip.style.top = (e.clientY + 14) + "px";
  }});
  el.addEventListener("mouseleave", () => {{ tip.style.display = "none"; }});
}});
</script></body></html>"""
    Path(out).write_text(page)
    print(f"wrote {out}")


if __name__ == "__main__":
    render(sys.argv[1], sys.argv[2])
