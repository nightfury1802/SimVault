"""
SimVault visualization helpers.

generate_model_graph_html()  → self-contained D3 force-graph HTML for simvault.graph.json
sync_kb_visuals()            → copies graphify-out visuals into docs/ and writes an index
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path


# ── colour palette by node / edge type ─────────────────────────────────────
_NODE_COLORS = {
    "subsystem": "#4f8ef7",
    "port":      "#94c6ff",
}
_EDGE_COLORS = {
    "has_port":             "#aaaaaa",
    "compatible_with":      "#22c55e",
    "fidelity_chain":       "#f59e0b",
    "requires_input_from":  "#e879f9",
    "analysis_context_match": "#06b6d4",
}
_EDGE_WIDTHS = {
    "has_port": 0.8,
    "compatible_with": 2,
    "fidelity_chain": 2.5,
    "requires_input_from": 1.5,
    "analysis_context_match": 1.5,
}


def generate_model_graph_html(graph_data: dict) -> str:
    """Return a self-contained HTML page with a D3 v7 force-directed graph."""
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", graph_data.get("links", []))

    # Attach display labels
    for n in nodes:
        nid = n.get("id", "")
        if n.get("type") == "subsystem":
            n["_label"] = nid
            n["_size"]  = 14
        else:
            # port nodes: show canonical_name if present
            n["_label"] = n.get("canonical_name") or nid.split("/")[-1]
            n["_size"]  = 6

    nodes_json = json.dumps(nodes)
    edges_json = json.dumps(edges)
    colors_json = json.dumps(_NODE_COLORS)
    edge_colors_json = json.dumps(_EDGE_COLORS)
    edge_widths_json = json.dumps(_EDGE_WIDTHS)

    n_sub  = sum(1 for n in nodes if n.get("type") == "subsystem")
    n_port = sum(1 for n in nodes if n.get("type") == "port")
    n_compat = sum(1 for e in edges if e.get("type") == "compatible_with")
    n_chain  = sum(1 for e in edges if e.get("type") == "fidelity_chain")

    legend_items = "\n".join(
        f'<span class="leg-dot" style="background:{c}"></span>{t}'
        for t, c in {**_NODE_COLORS, **{k: v for k, v in _EDGE_COLORS.items() if k != "has_port"}}.items()
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>SimVault — Model Graph</title>
<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #0f172a; color: #e2e8f0; font-family: system-ui, sans-serif; }}
  #header {{ padding: 14px 20px; background: #1e293b; border-bottom: 1px solid #334155;
             display: flex; align-items: center; gap: 20px; flex-wrap: wrap; }}
  h1 {{ font-size: 1.1rem; font-weight: 600; }}
  .stat {{ font-size: .78rem; color: #94a3b8; }}
  .stat b {{ color: #e2e8f0; }}
  #legend {{ display: flex; gap: 14px; flex-wrap: wrap; font-size: .75rem; color: #94a3b8; }}
  .leg-dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%;
              margin-right: 4px; vertical-align: middle; }}
  #canvas {{ width: 100vw; height: calc(100vh - 54px); }}
  .node-label {{ pointer-events: none; fill: #e2e8f0; font-size: 11px;
                 text-shadow: 0 1px 3px #0f172a; }}
  .tooltip {{ position: absolute; background: #1e293b; border: 1px solid #334155;
              border-radius: 6px; padding: 8px 12px; font-size: .78rem; pointer-events: none;
              display: none; max-width: 320px; line-height: 1.5; }}
  .tooltip b {{ color: #60a5fa; }}
</style>
</head>
<body>
<div id="header">
  <h1>SimVault — Model Graph</h1>
  <div class="stat"><b>{n_sub}</b> subsystems &nbsp;|&nbsp; <b>{n_port}</b> ports &nbsp;|&nbsp;
    <b>{n_compat}</b> compatible_with &nbsp;|&nbsp; <b>{n_chain}</b> fidelity_chain</div>
  <div id="legend">{legend_items}</div>
</div>
<svg id="canvas"></svg>
<div class="tooltip" id="tip"></div>
<script>
const nodes = {nodes_json};
const edges = {edges_json};
const nodeColors = {colors_json};
const edgeColors = {edge_colors_json};
const edgeWidths = {edge_widths_json};

const svg = d3.select("#canvas");
const W = window.innerWidth, H = window.innerHeight - 54;
svg.attr("viewBox", [0, 0, W, H]);

const g = svg.append("g");
svg.call(d3.zoom().scaleExtent([0.1, 8]).on("zoom", e => g.attr("transform", e.transform)));

const tip = document.getElementById("tip");

// index nodes by id
const nodeById = {{}};
nodes.forEach(n => nodeById[n.id] = n);

const link = g.append("g").selectAll("line")
  .data(edges).join("line")
  .attr("stroke", d => edgeColors[d.type] || "#555")
  .attr("stroke-width", d => edgeWidths[d.type] || 1)
  .attr("stroke-opacity", 0.6);

const node = g.append("g").selectAll("circle")
  .data(nodes).join("circle")
  .attr("r", d => d._size || 6)
  .attr("fill", d => nodeColors[d.type] || "#888")
  .attr("stroke", "#1e293b").attr("stroke-width", 1.5)
  .style("cursor", "pointer")
  .on("mouseover", (e, d) => {{
    tip.style.display = "block";
    tip.style.left = (e.pageX + 12) + "px";
    tip.style.top  = (e.pageY - 10) + "px";
    const rows = Object.entries(d)
      .filter(([k]) => !k.startsWith("_") && k !== "index" && k !== "vx" && k !== "vy" && k !== "fx" && k !== "fy")
      .map(([k,v]) => `<b>${{k}}</b>: ${{JSON.stringify(v)}}`).join("<br>");
    tip.innerHTML = rows;
  }})
  .on("mousemove", e => {{
    tip.style.left = (e.pageX + 12) + "px";
    tip.style.top  = (e.pageY - 10) + "px";
  }})
  .on("mouseout", () => tip.style.display = "none")
  .call(d3.drag()
    .on("start", (e, d) => {{ if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }})
    .on("drag",  (e, d) => {{ d.fx = e.x; d.fy = e.y; }})
    .on("end",   (e, d) => {{ if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }}));

// labels only for subsystem nodes
const label = g.append("g").selectAll("text")
  .data(nodes.filter(n => n.type === "subsystem")).join("text")
  .attr("class", "node-label")
  .attr("dy", "-10px")
  .text(d => d._label);

const sim = d3.forceSimulation(nodes)
  .force("link", d3.forceLink(edges)
    .id(d => d.id)
    .distance(d => d.type === "has_port" ? 30 : d.type === "compatible_with" ? 60 : 120)
    .strength(d => d.type === "has_port" ? 0.8 : 0.3))
  .force("charge", d3.forceManyBody().strength(d => d.type === "subsystem" ? -400 : -60))
  .force("center", d3.forceCenter(W / 2, H / 2))
  .force("collision", d3.forceCollide(d => d._size + 4))
  .on("tick", () => {{
    link.attr("x1", d => d.source.x).attr("y1", d => d.source.y)
        .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
    node.attr("cx", d => d.x).attr("cy", d => d.y);
    label.attr("x", d => d.x).attr("y", d => d.y);
  }});

window.addEventListener("resize", () => {{
  const w = window.innerWidth, h = window.innerHeight - 54;
  svg.attr("viewBox", [0, 0, w, h]);
  sim.force("center", d3.forceCenter(w/2, h/2)).alpha(0.1).restart();
}});
</script>
</body>
</html>"""


def sync_kb_visuals(docs_dir: Path, graphify_out: Path) -> int:
    """
    Copy graphify-out visuals into docs/ and write a docs/index.html portal.
    Returns number of files synced.
    """
    docs_dir.mkdir(parents=True, exist_ok=True)
    synced = 0

    for fname in ("graph.html", "GRAPH_TREE.html", "GRAPH_REPORT.md"):
        src = graphify_out / fname
        if src.exists():
            dst = docs_dir / fname
            shutil.copy2(src, dst)
            synced += 1

    # Write index.html portal
    model_exists = (docs_dir / "model_graph.html").exists()
    graph_exists  = (docs_dir / "graph.html").exists()
    tree_exists   = (docs_dir / "GRAPH_TREE.html").exists()
    report_exists = (docs_dir / "GRAPH_REPORT.md").exists()

    cards = ""
    if model_exists:
        cards += _card("Model Graph", "model_graph.html",
                       "Subsystem ports, wire compatibility, fidelity chains", "#4f8ef7")
    if graph_exists:
        cards += _card("KB Network", "graph.html",
                       "Interactive D3 knowledge graph — sessions, pitfalls, code", "#22c55e")
    if tree_exists:
        cards += _card("KB Tree", "GRAPH_TREE.html",
                       "Collapsible tree view of all KB nodes", "#f59e0b")
    if report_exists:
        cards += _card("Graph Report", "GRAPH_REPORT.md",
                       "Statistics: node/edge counts, top hubs", "#94a3b8")

    (docs_dir / "index.html").write_text(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>SimVault Docs</title>
<style>
  body {{ background:#0f172a; color:#e2e8f0; font-family:system-ui,sans-serif;
         padding:40px 5vw; }}
  h1 {{ font-size:1.6rem; margin-bottom:8px; }}
  p.sub {{ color:#94a3b8; margin-bottom:36px; font-size:.9rem; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); gap:20px; }}
  .card {{ background:#1e293b; border:1px solid #334155; border-radius:10px;
           padding:22px; text-decoration:none; color:inherit; display:block;
           transition:border-color .15s; }}
  .card:hover {{ border-color:#4f8ef7; }}
  .card-dot {{ width:12px; height:12px; border-radius:50%; margin-bottom:12px; }}
  .card h2 {{ font-size:1rem; margin-bottom:6px; }}
  .card p {{ font-size:.8rem; color:#94a3b8; }}
</style>
</head>
<body>
<h1>SimVault — Visualizations</h1>
<p class="sub">Auto-generated by <code>simvault kb-update</code></p>
<div class="grid">{cards}</div>
</body>
</html>""")
    return synced


def _card(title: str, href: str, desc: str, color: str) -> str:
    return (f'<a class="card" href="{href}">'
            f'<div class="card-dot" style="background:{color}"></div>'
            f'<h2>{title}</h2><p>{desc}</p></a>')
