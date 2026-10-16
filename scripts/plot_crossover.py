#!/usr/bin/env python3
"""
Crossover chart: graph (broadcast) vs hypergraph (relay) as team size grows.
Three small multiples, one y-axis each: score, messages read per agent (log scale),
cost per game. Self-contained HTML with hover tooltips, light/dark mode, data table.

  python scripts/plot_crossover.py runs/pilot4/crossover.jsonl runs/pilot4/crossover.html
"""

import html
import json
import math
import random
import sys
from pathlib import Path

SERIES = [("relay-global", "Relay (hypergraph)", "var(--series-1)"),
          ("broadcast", "Broadcast (graph)", "var(--series-2)")]
W, H = 400, 260
M = {"l": 58, "r": 120, "t": 46, "b": 42}


def ci(xs, reps=4000):
    rng = random.Random(0)
    means = sorted(sum(rng.choice(xs) for _ in xs) / len(xs) for _ in range(reps))
    return means[int(0.025 * reps)], means[int(0.975 * reps) - 1]


def nice(v):
    mag = 10 ** math.floor(math.log10(v))
    return next(s * mag for s in (1, 2, 2.5, 4, 5, 10) if v <= s * mag)


def mean(xs):
    return sum(xs) / len(xs)


def panel(title, key, rows, sizes, fmt, log=False, ymin=0.0, ymax=None, note=""):
    pw, ph = W - M["l"] - M["r"], H - M["t"] - M["b"]
    vals = [r[key] for r in rows]
    top = ymax or nice(max(vals) * 1.05)
    lo_log, hi_log = (math.log10(max(1, min(vals)) / 1.5), math.log10(max(vals) * 1.5)) if log else (0, 0)

    def x(n):
        a, b = math.log2(sizes[0]), math.log2(sizes[-1])
        return M["l"] + (math.log2(n) - a) / (b - a) * pw

    def y(v):
        if log:
            return M["t"] + ph - (math.log10(max(v, 1)) - lo_log) / (hi_log - lo_log) * ph
        return M["t"] + ph - (v - ymin) / (top - ymin) * ph

    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{html.escape(title)}">',
           f'<text x="{M["l"]}" y="16" class="ptitle">{html.escape(title)}</text>']
    if note:
        out.append(f'<text x="{M["l"]}" y="31" class="tick">{note}</text>')
    ticks = ([10 ** e for e in range(math.ceil(lo_log), math.floor(hi_log) + 1)] if log
             else [ymin + (top - ymin) * i / 4 for i in range(5)])
    for v in ticks:
        out.append(f'<line x1="{M["l"]}" x2="{M["l"] + pw}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/>')
        out.append(f'<text x="{M["l"] - 8}" y="{y(v) + 4:.1f}" class="tick" text-anchor="end">{fmt(v)}</text>')
    for n in sizes:
        out.append(f'<text x="{x(n):.1f}" y="{M["t"] + ph + 18}" class="tick" text-anchor="middle">{n}</text>')
    out.append(f'<text x="{M["l"] + pw / 2}" y="{H - 4}" class="axis" text-anchor="middle">agents on the team</text>')
    ends = []
    for comms, label, color in SERIES:
        pts = []
        for n in sizes:
            rs = [r for r in rows if r["comms"] == comms and r["size"] == n]
            if rs:
                pts.append((n, mean([r[key] for r in rs]), rs))
        if not pts:
            continue
        for n, _m, rs in pts:  # CI whiskers and individual seeds, behind the line
            if key == "score" and len(rs) > 1:
                a, b = ci([r[key] for r in rs])
                out.append(f'<line x1="{x(n):.1f}" x2="{x(n):.1f}" y1="{y(a):.1f}" y2="{y(b):.1f}" '
                           f'stroke="{color}" stroke-width="2" opacity="0.45"/>')
            for r in rs:
                out.append(f'<circle cx="{x(n):.1f}" cy="{y(r[key]):.1f}" r="2.5" fill="{color}" opacity="0.35"/>')
        d = " ".join(f"{'M' if i == 0 else 'L'}{x(n):.1f},{y(m):.1f}" for i, (n, m, _) in enumerate(pts))
        out.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"/>')
        for n, m, rs in pts:
            seeds = ", ".join(fmt(r[key]) for r in rs)
            tip = f"{label} · {n} agents: {fmt(m)} (seeds: {seeds})"
            out.append(f'<circle cx="{x(n):.1f}" cy="{y(m):.1f}" r="5" fill="{color}" class="pt" '
                       f'data-tip="{html.escape(tip)}"/>')
        ends.append([y(pts[-1][1]), label, x(pts[-1][0])])
    ends.sort()
    for i in range(1, len(ends)):
        ends[i][0] = max(ends[i][0], ends[i - 1][0] + 14)
    for ly, label, lx in ends:
        out.append(f'<text x="{lx + 10:.1f}" y="{ly + 4:.1f}" class="dlabel">{html.escape(label)}</text>')
    out.append("</svg>")
    return "\n".join(out)


def render(src, dst):
    rows = [json.loads(line) for line in Path(src).read_text().splitlines() if line.strip()]
    for r in rows:
        r["read_per_agent"] = r["inbox_per_agent"]
    sizes = sorted({r["size"] for r in rows})
    model = rows[0].get("model", "")
    panels = [
        panel("Score (share of questions answered correctly)", "score", rows, sizes,
              lambda v: f"{v:.2f}", ymin=0, ymax=1, note="dots = seeds, bars = 95% CI"),
        panel("Messages each agent had to read", "read_per_agent", rows, sizes,
              lambda v: f"{v:,.0f}", log=True, note="log scale"),
        panel("Cost per game", "cost_usd", rows, sizes, lambda v: f"${v:.2f}"),
    ]
    table_rows = []
    for n in sizes:
        for comms, label, _ in SERIES:
            rs = [r for r in rows if r["comms"] == comms and r["size"] == n]
            if rs:
                a, b = ci([r["score"] for r in rs])
                table_rows.append(
                    f"<tr><td>{n}</td><td>{label}</td><td>{len(rs)}</td>"
                    f"<td>{mean([r['score'] for r in rs]):.3f}</td><td>[{a:.3f}, {b:.3f}]</td>"
                    f"<td>{mean([r['read_per_agent'] for r in rs]):,.0f}</td>"
                    f"<td>{mean([r['tokens_per_agent'] for r in rs]):,.0f}</td>"
                    f"<td>${mean([r['cost_usd'] for r in rs]):.2f}</td></tr>")
    legend = "".join(f'<span class="key"><svg width="26" height="10"><line x1="1" x2="25" y1="5" y2="5" '
                     f'stroke="{c}" stroke-width="2"/></svg>{lbl}</span>' for _, lbl, c in SERIES)
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Graph vs hypergraph crossover</title>
<style>
.viz-root {{ color-scheme: light; --surface-1:#fcfcfb; --text-primary:#0b0b0b; --text-secondary:#52514e;
  --grid:#e6e5e1; --series-1:#2a78d6; --series-2:#eb6834; }}
@media (prefers-color-scheme: dark) {{ :root:where(:not([data-theme="light"])) .viz-root {{ color-scheme: dark;
  --surface-1:#1a1a19; --text-primary:#f0efec; --text-secondary:#c3c2b7; --grid:#2e2e2b;
  --series-1:#3987e5; --series-2:#d95926; }} }}
:root[data-theme="dark"] .viz-root {{ color-scheme: dark; --surface-1:#1a1a19; --text-primary:#f0efec;
  --text-secondary:#c3c2b7; --grid:#2e2e2b; --series-1:#3987e5; --series-2:#d95926; }}
body {{ margin:0; }}
.viz-root {{ background:var(--surface-1); color:var(--text-primary); min-height:100vh; padding:24px 28px;
  font:14px/1.45 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; }}
h1 {{ font-size:20px; margin:0 0 4px; }} .sub {{ color:var(--text-secondary); margin:0 0 12px; max-width:880px; }}
.legend {{ display:flex; gap:18px; margin:0 0 8px; color:var(--text-secondary); }}
.key {{ display:inline-flex; align-items:center; gap:6px; white-space:nowrap; }}
.wrap {{ display:grid; grid-template-columns:repeat(3, minmax(300px, 1fr)); gap:10px 22px; max-width:1300px; }}
svg {{ width:100%; height:auto; overflow:visible; }}
.ptitle {{ font-size:12.5px; font-weight:600; fill:var(--text-primary); }}
.tick {{ font-size:11px; fill:var(--text-secondary); font-variant-numeric:tabular-nums; }}
.axis {{ font-size:11px; fill:var(--text-secondary); }} .dlabel {{ font-size:11px; fill:var(--text-primary); }}
.grid {{ stroke:var(--grid); }} .pt {{ stroke:var(--surface-1); stroke-width:2; }} .pt:hover {{ r:7; }}
#tip {{ position:fixed; pointer-events:none; background:var(--text-primary); color:var(--surface-1);
  padding:5px 8px; border-radius:6px; font-size:12px; display:none; max-width:340px; }}
table {{ border-collapse:collapse; margin-top:10px; font-size:13px; font-variant-numeric:tabular-nums; }}
th, td {{ padding:4px 10px; text-align:right; border-bottom:1px solid var(--grid); }}
th:nth-child(2), td:nth-child(2) {{ text-align:left; }}
details {{ margin-top:14px; }} summary {{ cursor:pointer; color:var(--text-secondary); }}
</style></head><body><div class="viz-root">
<h1>Graph vs hypergraph communication: the crossover</h1>
<p class="sub">Distributed-knowledge task, {html.escape(model)} agents. Broadcast passes raw messages to everyone (graph);
the relay is an LLM channel that sends each agent a digest of only what it needs (hypergraph). Same agents, prompts,
attention limit (40 messages per turn), and seeds; relay cost is included. {len(rows)} games, 4 paired seeds per point.</p>
<div class="legend">{legend}</div>
<div class="wrap">{''.join(panels)}</div>
<details open><summary>Data table</summary><table>
<tr><th>Agents</th><th>Condition</th><th>Seeds</th><th>Score</th><th>95% CI</th><th>Read/agent</th><th>Tokens/agent</th><th>$/game</th></tr>
{''.join(table_rows)}</table></details><div id="tip"></div></div>
<script>
const tip = document.getElementById("tip");
document.querySelectorAll(".pt").forEach((el) => {{
  el.addEventListener("mousemove", (e) => {{ tip.textContent = el.dataset.tip; tip.style.display = "block";
    tip.style.left = (e.clientX + 14) + "px"; tip.style.top = (e.clientY + 14) + "px"; }});
  el.addEventListener("mouseleave", () => {{ tip.style.display = "none"; }});
}});
</script></body></html>"""
    Path(dst).write_text(page)
    print(f"wrote {dst}")


if __name__ == "__main__":
    render(sys.argv[1], sys.argv[2])
