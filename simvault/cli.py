"""SimVault CLI — index .slx libraries and query for reusable components."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click

from simvault.canonicalizer.canonicalize import canonicalize_all
from simvault.graph.build_graph import build_graph, save_graph
from simvault.query.query import format_result, get_assembly_context, query as _query
from simvault.validator.validate_ports import PortSpec, load_port, validate_wire
from simvault.vectors.index import build_index, query_index


@click.group()
def cli():
    """SimVault — Simulink model knowledge graph and assembly assistant."""


# ---------------------------------------------------------------------------
# simvault index <model_dir>
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("model_dir")
@click.option("--extracted-dir", default="extracted",   help="Output dir for extracted JSON")
@click.option("--kb-dir",        default="kb/models",   help="Output dir for Markdown specs")
@click.option("--store-dir",     default="store",       help="Vector store directory")
@click.option("--graph-path",    default="simvault.graph.json", help="Graph output path")
@click.option("--lock-file",     default="simvault.lock.json",  help="Lock file path")
@click.option("--skip-matlab",   is_flag=True,          help="Skip MATLAB extraction (use existing JSONs)")
def index(model_dir, extracted_dir, kb_dir, store_dir, graph_path, lock_file, skip_matlab):
    """Index a directory of .slx files into SimVault."""
    import os

    if not skip_matlab:
        # Run MATLAB extractor via matlab-mcp-proxy or direct matlab call
        click.echo(f"Running MATLAB extractor on: {model_dir}")
        _run_matlab_extractor(model_dir, extracted_dir, lock_file)
    else:
        click.echo("Skipping MATLAB extraction (--skip-matlab).")

    click.echo(f"Canonicalizing JSON in: {extracted_dir}")
    canonicalize_all(extracted_dir, kb_dir)

    click.echo("Building knowledge graph...")
    G = build_graph(extracted_dir)
    save_graph(G, graph_path)

    from simvault.graph.build_graph import graph_summary
    click.echo(graph_summary(G))

    click.echo(f"Building vector index into: {store_dir}")
    build_index(extracted_dir, store_dir=store_dir)

    click.echo("Done. SimVault index ready.")


def _run_matlab_extractor(model_dir: str, extracted_dir: str, lock_file: str) -> None:
    """Invoke MATLAB to run extract_metadata.m. Falls back to a stub if MATLAB not available."""
    parser_dir = Path(__file__).parent / "parser"
    matlab_script = (
        f"addpath('{parser_dir}'); "
        f"extract_metadata('{model_dir}', '{extracted_dir}', '{lock_file}'); "
        f"exit;"
    )
    try:
        result = subprocess.run(
            ["matlab", "-batch", matlab_script],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            click.echo(f"MATLAB error:\n{result.stderr}", err=True)
        else:
            click.echo(result.stdout)
    except FileNotFoundError:
        click.echo(
            "WARNING: 'matlab' not found on PATH. "
            "Skipping MATLAB extraction. Make sure extracted/ JSONs exist.",
            err=True,
        )
    except subprocess.TimeoutExpired:
        click.echo("WARNING: MATLAB extraction timed out.", err=True)


# ---------------------------------------------------------------------------
# simvault query <text>
# ---------------------------------------------------------------------------

@cli.command("query")
@click.argument("query_text")
@click.option("--fidelity",  default=None, help="Filter: detailed | simplified | lookup")
@click.option("--analysis",  default=None, help="Filter: torque_accuracy | efficiency | thermal | drive_cycle")
@click.option("--solver",    default=None, help="Filter: continuous | discrete | steady_state")
@click.option("--top-k",     default=5,    help="Max results")
@click.option("--store-dir", default="store",               help="Vector store directory")
@click.option("--graph-path",default="simvault.graph.json", help="Graph path")
def query_cmd(query_text, fidelity, analysis, solver, top_k, store_dir, graph_path):
    """Search SimVault for subsystems matching a natural language description."""
    result = _query(
        text=query_text,
        fidelity_tier=fidelity,
        analysis_type=analysis,
        solver_contract=solver,
        top_k=top_k,
        store_dir=store_dir,
        graph_path=graph_path,
    )
    click.echo(format_result(result))


# ---------------------------------------------------------------------------
# simvault validate --src <id/port> --dst <id/port>
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--src", required=True, help="Source: subsystem_id/canonical_port_name")
@click.option("--dst", required=True, help="Destination: subsystem_id/canonical_port_name")
@click.option("--json-dir", default="extracted", help="Extracted JSON directory")
def validate(src, dst, json_dir):
    """Validate a proposed wire between two canonical port names."""
    src_ss, src_port = _parse_port_arg(src)
    dst_ss, dst_port = _parse_port_arg(dst)
    try:
        sp = load_port(json_dir, src_ss, src_port)
        dp = load_port(json_dir, dst_ss, dst_port)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    vr = validate_wire(sp, dp)
    color = {"PASS": "green", "WARN": "yellow", "BLOCK": "red"}[vr.result]
    click.echo(click.style(vr.result, fg=color, bold=True) + f"  {vr.reason}")
    if vr.required_bridge_block:
        click.echo(f"  Bridge required: {vr.required_bridge_block}")
    if vr.gain_factor is not None:
        click.echo(f"  Gain factor:     {vr.gain_factor:.6f}")


def _parse_port_arg(arg: str) -> tuple[str, str]:
    """Parse 'SubsystemId/port_name' → (subsystem_id, port_name)."""
    parts = arg.split("/", 1)
    if len(parts) != 2:
        raise click.BadParameter(f"Expected format: subsystem_id/port_canonical_name, got: {arg}")
    return parts[0], parts[1]


# ---------------------------------------------------------------------------
# simvault context <id1> <id2> ...
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("subsystem_ids", nargs=-1, required=True)
@click.option("--json-dir",   default="extracted",          help="Extracted JSON directory")
@click.option("--graph-path", default="simvault.graph.json", help="Graph path")
def context(subsystem_ids, json_dir, graph_path):
    """Get assembly context for a set of subsystems (ports, wires, solver info)."""
    import json
    ctx = get_assembly_context(list(subsystem_ids), json_dir=json_dir, graph_path=graph_path)
    click.echo(json.dumps(ctx, indent=2))


@cli.command("kb-update")
@click.option("--skip-graphify", is_flag=True, help="Skip graphify update step")
@click.option("--skip-llm", is_flag=True, help="Skip LLM fact extraction")
def kb_update(skip_graphify, skip_llm):
    """Full KB pipeline: export → graphify → link-entities → turbovec."""
    import subprocess
    import os
    from pathlib import Path
    from simvault.knowledge.export import run as export_run
    from simvault.knowledge.indexer import run as index_run
    from simvault.graph.link_entities import run as link_run
    simscape_root = Path(__file__).parent.parent.parent
    click.echo("→ Exporting lean-ctx atoms...")
    export_run()
    if not skip_llm:
        click.echo("→ LLM fact extraction...")
        try:
            from simvault.knowledge.llm_extract import run as llm_run
            n = llm_run()
            click.echo(f"  {n} facts extracted.")
        except Exception as e:
            click.echo(f"  LLM skipped: {e}")
    if not skip_graphify:
        click.echo("→ Running graphify update...")
        subprocess.run(
            ["graphify", "update", "."],
            env={**os.environ, "GRAPHIFY_VIZ_NODE_LIMIT": "20000"},
            cwd=str(simscape_root),
        )
        subprocess.run(["graphify", "tree"], cwd=str(simscape_root))
    click.echo("→ Building cross-edges...")
    click.echo(f"  {link_run()} edges written.")
    click.echo("→ Indexing knowledge chunks...")
    click.echo(f"  {index_run()} new chunks embedded.")
    click.echo("→ Regenerating visualizations...")
    try:
        import json
        from simvault.viz import generate_model_graph_html, sync_kb_visuals
        docs = Path(__file__).parent.parent / "docs"
        docs.mkdir(exist_ok=True)
        gpath = Path(__file__).parent.parent / "simvault.graph.json"
        if gpath.exists():
            html = generate_model_graph_html(json.loads(gpath.read_text()))
            (docs / "model_graph.html").write_text(html)
        sync_kb_visuals(docs, simscape_root / "graphify-out")
        click.echo("  docs/ updated.")
    except Exception as e:
        click.echo(f"  viz skipped: {e}")
    click.echo("✓ KB update complete.")


@cli.command("kb-query")
@click.argument("query")
@click.option("--k", default=10, help="Max results")
def kb_query_cmd(query, k):
    """Unified KB search: semantic + BM25 + graph, fused with RRF."""
    from simvault.retrieval.unified import UnifiedQuery
    results = UnifiedQuery().search(query, k=k)
    if not results:
        click.echo("No results.")
        return
    for i, r in enumerate(results, 1):
        score = r.get("effective_score", r.get("score", 0))
        click.echo(f"\n[{i}] {score:.3f}  [{r.get('mode','?')}]  {r.get('source','')}")
        click.echo(f"    {r.get('text','')[:200]}")


@cli.command("kb-extract-session")
@click.argument("session_index", type=int, required=False)
def kb_extract_session(session_index):
    """List sessions or extract facts from session N via LLM."""
    from simvault.knowledge.sessions import list_sessions
    from simvault.knowledge.llm_extract import run as llm_run
    sessions = list_sessions()
    if not sessions:
        click.echo("No sessions found.")
        return
    if session_index is None:
        for i, p in enumerate(sessions):
            click.echo(f"[{i}] {p.name}  ({p.stat().st_size//1024} KB)")
        return
    click.echo(f"Extracting from: {sessions[session_index].name}")
    click.echo(f"✓ {llm_run(session_path=sessions[session_index])} facts written.")


@cli.command("viz")
@click.option("--open", "open_browser", is_flag=True, help="Open in browser after generating")
@click.option("--graph-path", default="simvault.graph.json", help="Model graph path")
def viz_cmd(open_browser, graph_path):
    """Generate HTML visualizations for model graph and KB graph."""
    import json, os
    from pathlib import Path
    from simvault.viz import generate_model_graph_html, sync_kb_visuals
    _root = Path(__file__).parent.parent
    docs = _root / "docs"
    docs.mkdir(exist_ok=True)
    # Model graph
    gpath = Path(graph_path)
    if gpath.exists():
        html = generate_model_graph_html(json.loads(gpath.read_text()))
        out = docs / "model_graph.html"
        out.write_text(html)
        click.echo(f"✓ model_graph.html  ({gpath.stat().st_size//1024} KB graph)")
    else:
        click.echo(f"  model graph not found at {graph_path} — run simvault index first")
    # KB visuals (symlinks to graphify-out)
    n = sync_kb_visuals(docs, _root.parent / "graphify-out")
    click.echo(f"✓ {n} KB visual(s) synced → docs/")
    if open_browser:
        import webbrowser
        webbrowser.open(str(docs / "index.html"))


if __name__ == "__main__":
    cli()
