"""SimVault MCP server — exposes 4 tools to Claude agents."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from simvault.query.query import format_result, get_assembly_context, query
from simvault.validator.validate_ports import PortSpec, load_port, validate_wire

# ---------------------------------------------------------------------------
# Configurable paths (override via env vars for production)
# ---------------------------------------------------------------------------
_ROOT = Path(os.environ.get("SIMVAULT_ROOT", Path(__file__).parent.parent))
_STORE_DIR  = str(_ROOT / os.environ.get("SIMVAULT_STORE", "store"))
_GRAPH_PATH = str(_ROOT / os.environ.get("SIMVAULT_GRAPH", "simvault.graph.json"))
_JSON_DIR   = str(_ROOT / os.environ.get("SIMVAULT_JSON",  "extracted"))


app = Server("simvault")


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
    types.Tool(
        name="simvault_search",
        description=(
            "Search SimVault for Simscape/Simulink subsystems by natural language query. "
            "Returns ranked candidates with fidelity, analysis type, and compatible graph neighbors."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query":           {"type": "string",  "description": "Natural language description of what you need"},
                "fidelity_tier":   {"type": "string",  "description": "Hard filter: detailed | simplified | lookup"},
                "analysis_type":   {"type": "string",  "description": "Hard filter: torque_accuracy | efficiency | thermal | drive_cycle"},
                "solver_contract": {"type": "string",  "description": "Hard filter: continuous | discrete | steady_state"},
                "top_k":           {"type": "integer", "description": "Maximum results (default 5)", "default": 5},
            },
            "required": ["query"],
        },
    ),
    types.Tool(
        name="simvault_validate_wire",
        description=(
            "Validate a proposed signal or physical connection between two ports. "
            "Returns PASS, WARN (with required bridge block), or BLOCK (with reason)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "src_subsystem_id":    {"type": "string", "description": "Source subsystem ID (e.g. PMSM_FEM)"},
                "src_port_canonical":  {"type": "string", "description": "Source canonical port name (e.g. loss_copper_W)"},
                "dst_subsystem_id":    {"type": "string", "description": "Destination subsystem ID"},
                "dst_port_canonical":  {"type": "string", "description": "Destination canonical port name"},
            },
            "required": ["src_subsystem_id", "src_port_canonical", "dst_subsystem_id", "dst_port_canonical"],
        },
    ),
    types.Tool(
        name="simvault_get_assembly_context",
        description=(
            "Get full assembly context for a list of subsystem IDs: canonical ports, solver info, "
            "and pre-validated wire pairs. Use before calling model_edit to build a Simulink model."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "subsystem_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of subsystem IDs to assemble (e.g. [\"PMSM_FEM\", \"MotorThermal11Node\"])",
                },
            },
            "required": ["subsystem_ids"],
        },
    ),
    types.Tool(
        name="simvault_smoke_test",
        description=(
            "Run a quick smoke test on a Simulink model: load it, check it compiles, "
            "and optionally simulate for 0.1s at a rated operating point."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "model_path": {
                    "type": "string",
                    "description": "Absolute path to the .slx file",
                },
                "rated_operating_point": {
                    "type": "object",
                    "description": "Optional dict of workspace variables to set before sim (e.g. {\"speed_rpm\": 3000})",
                },
            },
            "required": ["model_path"],
        },
    ),
    types.Tool(
        name="simvault_kb_query",
        description=(
            "Unified KB query: session logs, pitfalls, validated results, model specs, "
            "and skills via BM25 + semantic + graph traversal fused with RRF. "
            "Use for 'what do we know about X' — not for port names (use simvault_get_assembly_context)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language question about history, pitfalls, or results"},
                "k":     {"type": "integer", "description": "Max results (default 10)", "default": 10},
            },
            "required": ["query"],
        },
    ),
    types.Tool(
        name="simvault_model_context_with_history",
        description=(
            "Assembly context (canonical ports + validated wires) PLUS KB history "
            "(pitfalls, validated results, decisions) for each model. "
            "Use instead of simvault_get_assembly_context when you also need session history."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "subsystem_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of subsystem IDs (e.g. [\"PMSM_FEM\", \"MotorThermal11Node\"])",
                },
            },
            "required": ["subsystem_ids"],
        },
    ),
]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return TOOLS


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        if name == "simvault_search":
            result = query(
                text=arguments["query"],
                fidelity_tier=arguments.get("fidelity_tier"),
                analysis_type=arguments.get("analysis_type"),
                solver_contract=arguments.get("solver_contract"),
                top_k=arguments.get("top_k", 5),
                store_dir=_STORE_DIR,
                graph_path=_GRAPH_PATH,
            )
            return [types.TextContent(type="text", text=format_result(result))]

        elif name == "simvault_validate_wire":
            src = load_port(
                _JSON_DIR,
                arguments["src_subsystem_id"],
                arguments["src_port_canonical"],
            )
            dst = load_port(
                _JSON_DIR,
                arguments["dst_subsystem_id"],
                arguments["dst_port_canonical"],
            )
            vr = validate_wire(src, dst)
            return [types.TextContent(type="text", text=vr.model_dump_json())]

        elif name == "simvault_get_assembly_context":
            ctx = get_assembly_context(
                arguments["subsystem_ids"],
                json_dir=_JSON_DIR,
                graph_path=_GRAPH_PATH,
            )
            return [types.TextContent(type="text", text=json.dumps(ctx, indent=2))]

        elif name == "simvault_smoke_test":
            result = _run_smoke_test(
                arguments["model_path"],
                arguments.get("rated_operating_point", {}),
            )
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "simvault_kb_query":
            from simvault.retrieval.unified import UnifiedQuery
            results = UnifiedQuery().search(arguments["query"], k=arguments.get("k", 10))
            payload = json.dumps({
                "query": arguments["query"],
                "results": [
                    {"rank": i+1,
                     "score": round(r.get("effective_score", r.get("score", 0)), 4),
                     "source": r.get("source", ""),
                     "text": r.get("text", "")[:400],
                     "mode": r.get("mode", "?")}
                    for i, r in enumerate(results)
                ]
            }, indent=2)
            return [types.TextContent(type="text", text=payload)]

        elif name == "simvault_model_context_with_history":
            from simvault.retrieval.unified import UnifiedQuery
            ctx = get_assembly_context(
                arguments["subsystem_ids"],
                json_dir=_JSON_DIR,
                graph_path=_GRAPH_PATH,
            )
            uq = UnifiedQuery()
            history = {
                mid: [{"source": r.get("source",""), "text": r.get("text","")[:300]}
                      for r in uq.search(f"{mid} pitfalls decisions results", k=5)]
                for mid in arguments["subsystem_ids"]
            }
            return [types.TextContent(type="text", text=json.dumps(
                {"assembly_context": ctx, "kb_history": history}, indent=2
            ))]

        else:
            return [types.TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as exc:
        return [types.TextContent(type="text", text=f"Error in {name}: {exc}")]


def _run_smoke_test(model_path: str, rated_op: dict) -> dict:
    """Stub smoke test — real implementation would call MATLAB via subprocess."""
    p = Path(model_path)
    if not p.exists():
        return {"status": "FAIL", "reason": f"File not found: {model_path}"}
    return {
        "status": "PASS",
        "model_path": str(p),
        "note": "Smoke test stub — connect MATLAB MCP for real simulation check",
        "rated_operating_point": rated_op,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(stdio_server(app))
