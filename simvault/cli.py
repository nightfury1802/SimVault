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
@click.option("--db-path",       default=".svdb",       help="ChromaDB persistence path")
@click.option("--graph-path",    default="simvault.graph.json", help="Graph output path")
@click.option("--lock-file",     default="simvault.lock.json",  help="Lock file path")
@click.option("--skip-matlab",   is_flag=True,          help="Skip MATLAB extraction (use existing JSONs)")
def index(model_dir, extracted_dir, kb_dir, db_path, graph_path, lock_file, skip_matlab):
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

    click.echo(f"Building vector index into: {db_path}")
    build_index(extracted_dir, db_path)

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
@click.option("--db-path",   default=".svdb",              help="ChromaDB path")
@click.option("--graph-path",default="simvault.graph.json", help="Graph path")
def query_cmd(query_text, fidelity, analysis, solver, top_k, db_path, graph_path):
    """Search SimVault for subsystems matching a natural language description."""
    result = _query(
        text=query_text,
        fidelity_tier=fidelity,
        analysis_type=analysis,
        solver_contract=solver,
        top_k=top_k,
        db_path=db_path,
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


if __name__ == "__main__":
    cli()
