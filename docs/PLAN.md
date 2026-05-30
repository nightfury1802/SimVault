# SimVault — Implementation Plan
**Target:** Phase 1 MVP (weekend build, ~19 hrs)  
**Spec:** `docs/superpowers/specs/2026-05-30-simvault-design.md`  
**Goal:** Given 5+ sample `.slx` files, agent can call `simvault_search` → `simvault_get_assembly_context` → `simulink_mcp.model_edit` → `simvault_smoke_test` and assemble a physically-valid model.

---

## Critical Path

```
extract_metadata.m
    → canonicalize.py
        → build_graph.py ──┐
        → index.py ────────┤
                           ├→ query.py
                           │       └→ mcp_server.py
        → validate_ports.py┘               └→ cli.py (thin wrapper)
```

Parser must run first. Canonicalizer feeds both graph and vector store. Validator feeds query engine. MCP server wraps everything. Tests run last.

---

## Day 1 — Saturday (Foundation)

### Task 1 — Project scaffolding
**File:** root  
**Effort:** 30 min  
**Create:**
```
SimVault/
├── simvault/
│   ├── __init__.py
│   ├── parser/        __init__.py
│   ├── canonicalizer/ __init__.py
│   ├── graph/         __init__.py
│   ├── vectors/       __init__.py
│   ├── validator/     __init__.py
│   ├── query/         __init__.py
│   ├── bridge/        __init__.py
├── hooks/
├── examples/pmsm_drive/    ← copy 3-5 sample .slx here
├── tests/
├── pyproject.toml
└── simvault.lock.json      ← start as {}
```

**`pyproject.toml` dependencies:**
```toml
[project]
name = "simvault"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "chromadb>=0.4",
    "sentence-transformers>=2.2",
    "networkx>=3.0",
    "click>=8.0",
    "numpy>=1.24",
    "mcp>=1.0",      # MCP SDK for Python
]
```

**Done when:** `pip install -e .` succeeds with no errors.

---

### Task 2 — Parser: `extract_metadata.m`
**File:** `simvault/parser/extract_metadata.m`  
**Effort:** 3–4 hrs  
**Depends on:** Task 1

This is the only MATLAB file. Everything else is Python.

**Implementation outline:**
```matlab
function extract_metadata(model_dir, output_dir, lock_file_path)
% Crawls model_dir for .slx files, extracts metadata JSON per model.
% Skips files whose SHA matches simvault.lock.json.

slx_files = dir(fullfile(model_dir, '**', '*.slx'));

for i = 1:length(slx_files)
    slx_path = fullfile(slx_files(i).folder, slx_files(i).name);

    % Skip build artifacts
    if contains(slx_path, {'slprj', '.git', '_archive'}), continue; end

    % Check hash
    current_hash = compute_sha256(slx_path);
    if hash_matches_lock(slx_path, current_hash, lock_file_path), continue; end

    % Extract
    load_system(slx_path);
    model_name = slx_files(i).name(1:end-4);
    metadata = extract_model_metadata(model_name, slx_path);
    save_json(metadata, fullfile(output_dir, [model_name '.json']));
    update_lock(slx_path, current_hash, lock_file_path);
    close_system(model_name, 0);
end
end
```

**`extract_model_metadata` must capture per SubSystem:**
- `identity`: name, path, description text
- `tags`: read structured lines from description (`fidelity_tier: ...`, `analysis_type: ...`, `solver_contract: ...`). If absent: fidelity inferred from block_count, solver_contract from solver name, analysis_type = `"untagged"`.
- `solver`: solver type, name, sample time
- `ports`: for each inport/outport of the subsystem:
  - `original_name` from port label
  - `port_type`: check if parent block is `simscape` physical port → `"physical"`, else `"signal"`
  - `direction`: `input` / `output`
  - `domain`: read from connected physical network type OR from description tag `domain: thermal`
  - `units`: read from description tag `units: W` OR leave `"unknown"`
- `block_count`: `length(find_system(subsystem_path, 'SearchDepth', 1))`
- `state_count`: from `getInitialState` or leave -1 if not computable without simulation
- `source_hash`: SHA-256 of the .slx file

**Domain detection heuristic** (for Simscape ports without explicit tags):
```matlab
% Check block library source of connected block
block_type = get_param(connected_block, 'ReferenceBlock');
if contains(block_type, 'fl_lib/Thermal'), domain = 'thermal';
elseif contains(block_type, 'fl_lib/Rotational'), domain = 'rotational_mechanical';
elseif contains(block_type, 'fl_lib/Electrical'), domain = 'electrical';
else, domain = 'signal';
end
```

**Output:** `extracted/<model_name>.json` matching the schema in spec §4.1.

**Done when:** Running `extract_metadata('examples/pmsm_drive', 'extracted', 'simvault.lock.json')` produces valid JSON files for each sample .slx.

---

### Task 3 — Canonicalizer: `canonicalize.py`
**File:** `simvault/canonicalizer/canonicalize.py`  
**Effort:** 2 hrs  
**Depends on:** Task 2

```python
CANONICAL_MAP = [
    # (regex_pattern, canonical_name, canonical_unit, scale_if_rpm)
    (r"omega|speed|w_out|w\b|rpm|n_shaft", "omega_shaft_rads", "rad/s",
     {"rpm": 2*pi/60, "RPM": 2*pi/60}),
    (r"torque|trq|^T$|t_out|tau",          "torque_shaft_Nm",  "N*m", {}),
    (r"T_winding|temp|temperature|t_pm|T_stator", "temperature_K", "K",
     {"_degC": "+273.15", "_C": "+273.15"}),
    (r"^id$|^Id$|i_d",   "id_current_A",  "A", {}),
    (r"^iq$|^Iq$|i_q",   "iq_current_A",  "A", {}),
    (r"Vdc|v_dc|VDC|DC_voltage", "vdc_V", "V", {}),
    (r"Q_copper|P_copper|Pcu",   "loss_copper_W", "W", {}),
    (r"Q_iron|P_iron|Pfe",       "loss_iron_W",   "W", {}),
    (r"flux_d|lambda_d|psi_d",   "flux_d_Wb",     "Wb", {}),
    (r"flux_q|lambda_q|psi_q",   "flux_q_Wb",     "Wb", {}),
]

def canonicalize_port(port: dict) -> dict:
    """
    Returns port with added fields:
      canonical_name: str
      canonical_units: str
      unit_mismatch: bool
      scale_factor: float | None
      canonicalized: bool
    """
```

**Markdown spec writer** (`write_markdown_spec`):
- Writes to `kb/models/<model>_<subsystem>.md`
- Frontmatter: fidelity_tier, analysis_type, solver_contract, source_file, source_hash, block_count, state_count
- Causal behavior summary: first paragraph of description OR auto-generated from port list
- Port interface table with canonical names, original names, domain, units, status
- Compatibility alerts for: unconnected thermal loss ports (if thermal domain input has no obvious EM partner)

**Done when:** `canonicalize('extracted/PMSMThermal.json')` produces `kb/models/PMSMThermal_MotorThermalModel.md` with correct canonical port names and a compatibility alert for `loss_iron_W`.

---

### Task 4 — Graph Builder: `build_graph.py`
**File:** `simvault/graph/build_graph.py`  
**Effort:** 3 hrs  
**Depends on:** Task 3

```python
import networkx as nx
import json

def build_graph(canonicalized_dir: str) -> nx.DiGraph:
    G = nx.DiGraph()

    for json_file in glob(canonicalized_dir + "/*.json"):
        meta = load_json(json_file)
        for subsystem in meta["subsystems"]:
            # Add SubsystemNode
            G.add_node(subsystem["id"], type="subsystem", **subsystem["tags"],
                       block_count=subsystem["block_count"],
                       state_count=subsystem["state_count"],
                       source_hash=subsystem["source_hash"])

            # Add PortNodes + has_port edges
            for port in subsystem["ports"]:
                port_id = f"{subsystem['id']}/ports/{port['canonical_name']}"
                G.add_node(port_id, type="port", **port)
                G.add_edge(subsystem["id"], port_id, type="has_port")

    # Compute compatible_with edges
    add_compatible_with_edges(G)

    # Compute fidelity_chain edges
    add_fidelity_chain_edges(G)

    # Compute requires_input_from edges (unconnected thermal inputs)
    add_requires_input_from_edges(G)

    return G
```

**`add_compatible_with_edges`:**
```python
def add_compatible_with_edges(G):
    port_nodes = [n for n,d in G.nodes(data=True) if d.get("type") == "port"]
    for p1, p2 in combinations(port_nodes, 2):
        d1, d2 = G.nodes[p1], G.nodes[p2]
        if (d1["domain"] == d2["domain"]                          # same domain
            and directions_compatible(d1["direction"], d2["direction"])  # input↔output
            and units_compatible(d1["canonical_units"], d2["canonical_units"])  # same or known scale
            and solver_contracts_compatible(                        # compatible solvers
                G.nodes[parent_subsystem(p1)],
                G.nodes[parent_subsystem(p2)])):
            G.add_edge(p1, p2, type="compatible_with",
                       scale_factor=get_scale_factor(d1["canonical_units"], d2["canonical_units"]))
```

**`add_fidelity_chain_edges`:**
```python
FIDELITY_SUFFIXES = ["_fem", "_avg", "_averaged", "_lookup", "_lut",
                     "_surrogate", "_nn", "_simplified", "_detailed",
                     "_highfidelity", "_hifi", "_reduced"]

def stem(name: str) -> str:
    for suffix in FIDELITY_SUFFIXES:
        if name.lower().endswith(suffix):
            return name[:len(name)-len(suffix)]
    return name

def add_fidelity_chain_edges(G):
    subsystems = [(n,d) for n,d in G.nodes(data=True) if d.get("type") == "subsystem"]
    for (n1,d1), (n2,d2) in combinations(subsystems, 2):
        if (stem(n1.split("/")[-1]) == stem(n2.split("/")[-1])
                and d1.get("fidelity_tier") != d2.get("fidelity_tier")):
            G.add_edge(n1, n2, type="fidelity_chain")
            G.add_edge(n2, n1, type="fidelity_chain")
```

**Save:** `nx.node_link_data(G)` → `simvault.graph.json`

**Done when:** Graph built from 5 sample models contains at least 1 `compatible_with` edge (motor copper loss → thermal copper loss input) and 1 `fidelity_chain` edge (FEM motor ↔ averaged motor).

---

## Day 2 — Sunday (Intelligence + Interface)

### Task 5 — Vector Store: `index.py`
**File:** `simvault/vectors/index.py`  
**Effort:** 1.5 hrs  
**Depends on:** Task 3

```python
import chromadb
from sentence_transformers import SentenceTransformer

MODEL = SentenceTransformer("BAAI/bge-small-en-v1.5")

def build_index(canonicalized_dir: str, db_path: str = ".svdb"):
    client = chromadb.PersistentClient(path=db_path)
    collection = client.get_or_create_collection("simvault")

    for json_file in glob(canonicalized_dir + "/*.json"):
        meta = load_json(json_file)
        for subsystem in meta["subsystems"]:
            doc = subsystem["causal_summary"]  # from markdown spec description
            collection.upsert(
                ids=[subsystem["id"]],
                documents=[doc],
                metadatas=[{
                    "fidelity_tier":    subsystem["tags"]["fidelity_tier"],
                    "analysis_type":    subsystem["tags"]["analysis_type"],
                    "solver_contract":  subsystem["tags"]["solver_contract"],
                    "source_file":      subsystem["source_file"],
                    "source_hash":      subsystem["source_hash"],
                    "block_count":      subsystem["block_count"],
                    "state_count":      subsystem["state_count"],
                    "has_iron_loss_input":   has_port(subsystem, "loss_iron_W", "input"),
                    "has_copper_loss_input": has_port(subsystem, "loss_copper_W", "input"),
                    "output_domains": ",".join(output_domains(subsystem)),
                    "input_domains":  ",".join(input_domains(subsystem)),
                }]
            )
```

**Incremental update:** Before upserting, check `source_hash` in collection metadata. If hash unchanged, skip. This makes re-indexing fast (< 3s for no changes).

**Done when:** `simvault index ./examples/pmsm_drive` populates `.svdb/` and `simvault query "PMSM thermal"` returns results.

---

### Task 6 — Validator: `validate_ports.py`
**File:** `simvault/validator/validate_ports.py`  
**Effort:** 2 hrs  
**Depends on:** Task 3

```python
UNIT_CONVERSION_TABLE = {
    ("rpm", "rad/s"):   2 * pi / 60,
    ("rad/s", "rpm"):   60 / (2 * pi),
    ("degC", "K"):      "+273.15",      # offset, not scale
    ("K", "degC"):      "-273.15",
    ("W", "kW"):        0.001,
    ("kW", "W"):        1000.0,
}

SOLVER_BRIDGE_TABLE = {
    ("continuous", "discrete"):  "Rate Transition",
    ("discrete", "continuous"):  "Rate Transition",
    ("continuous", "steady_state"): "Operating Point",
}

@dataclass
class ValidationResult:
    result: Literal["PASS", "WARN", "BLOCK"]
    reason: str = ""
    required_bridge_block: str = ""
    gain_factor: float | None = None

def validate_wire(src: PortSpec, dst: PortSpec) -> ValidationResult:
    # Rule 1: domain match (BLOCK)
    if src.domain != dst.domain:
        return ValidationResult("BLOCK",
            reason=f"Domain mismatch: {src.domain} → {dst.domain}. "
                   f"Cannot connect Simscape physical port to Simulink signal.")

    # Rule 2: direction (BLOCK)
    if not directions_compatible(src.direction, dst.direction):
        return ValidationResult("BLOCK",
            reason=f"Direction conflict: {src.direction} → {dst.direction}")

    # Rule 3: units (WARN with factor, BLOCK if unknown)
    if src.canonical_units != dst.canonical_units:
        factor = UNIT_CONVERSION_TABLE.get((src.canonical_units, dst.canonical_units))
        if factor is None:
            return ValidationResult("BLOCK",
                reason=f"Incompatible units: {src.canonical_units} ≠ {dst.canonical_units}")
        return ValidationResult("WARN",
            reason=f"Unit scale required: {src.canonical_units} → {dst.canonical_units}",
            required_bridge_block=f"Gain (factor: {factor})",
            gain_factor=float(factor) if isinstance(factor, (int, float)) else None)

    # Rule 4: solver contract (WARN with bridge)
    if src.solver_contract != dst.solver_contract:
        bridge = SOLVER_BRIDGE_TABLE.get((src.solver_contract, dst.solver_contract), "")
        return ValidationResult("WARN",
            reason=f"Solver mismatch: {src.solver_contract} ↔ {dst.solver_contract}",
            required_bridge_block=bridge)

    return ValidationResult("PASS")
```

**Done when:** `validate_wire(loss_copper_W_from_FEM, loss_copper_W_of_thermal)` returns PASS; `validate_wire(omega_shaft_rads, omega_shaft_rpm)` returns WARN with gain_factor=0.1047; `validate_wire(thermal_port, signal_port)` returns BLOCK.

---

### Task 7 — Query Engine: `query.py`
**File:** `simvault/query/query.py`  
**Effort:** 3 hrs  
**Depends on:** Tasks 4, 5, 6

```python
def query(
    text: str,
    fidelity_tier: str | None = None,
    analysis_type: str | None = None,
    solver_contract: str | None = None,
    top_k: int = 5,
    graph_depth: int = 2,
) -> QueryResult:

    # Step 1: hard filter (ChromaDB where clause — gates, not signals)
    where = {}
    if fidelity_tier:    where["fidelity_tier"]   = fidelity_tier
    if analysis_type:    where["analysis_type"]    = analysis_type
    if solver_contract:  where["solver_contract"]  = solver_contract

    # Step 2: semantic search on filtered set
    results = collection.query(
        query_texts=[text],
        n_results=top_k,
        where=where if where else None,
    )
    seed_ids = results["ids"][0]

    # Step 3: graph expansion
    G = load_graph("simvault.graph.json")
    subgraph_nodes = set(seed_ids)
    for node_id in seed_ids:
        # Expand compatible_with, fidelity_chain, requires_input_from
        for neighbor, edge_data in G.edges(node_id, data=True):
            if edge_data["type"] in ("compatible_with", "fidelity_chain",
                                     "requires_input_from", "analysis_context_match"):
                subgraph_nodes.add(neighbor)
                if graph_depth > 1:
                    for n2, _ in G.edges(neighbor, data=True):
                        subgraph_nodes.add(n2)

    # Step 4: validate candidate wires in subgraph
    validated_wires = []
    blocked_pairs = []
    for n1, n2, edata in G.subgraph(subgraph_nodes).edges(data=True):
        if edata["type"] == "compatible_with":
            p1 = PortSpec.from_node(G.nodes[n1])
            p2 = PortSpec.from_node(G.nodes[n2])
            vr = validate_wire(p1, p2)
            if vr.result == "BLOCK":
                blocked_pairs.append((n1, n2, vr))
            else:
                validated_wires.append((n1, n2, vr))

    # Step 5: assemble context for LLM
    return QueryResult(
        candidates=seed_ids,
        subgraph=G.subgraph(subgraph_nodes - {b[0] for b in blocked_pairs}),
        validated_wires=validated_wires,
        blocked_pairs=blocked_pairs,
        similarity_scores=dict(zip(seed_ids, results["distances"][0])),
    )
```

**Done when:** Query `"high-fidelity PMSM thermal continuous efficiency"` returns `MotorThermalModel` as candidate, `PMSMMotor_FEM` as compatible partner in subgraph, and validated wire list includes the copper loss connection as PASS.

---

### Task 8 — MCP Server: `mcp_server.py`
**File:** `simvault/mcp_server.py`  
**Effort:** 2 hrs  
**Depends on:** Tasks 5, 6, 7

Uses the `mcp` Python SDK (same pattern as the existing simulink MCP).

```python
from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types

app = Server("simvault")

@app.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "simvault_search":
        result = query(
            text=arguments["query"],
            fidelity_tier=arguments.get("fidelity_tier"),
            analysis_type=arguments.get("analysis_type"),
            solver_contract=arguments.get("solver_contract"),
            top_k=arguments.get("top_k", 5),
        )
        return [types.TextContent(type="text", text=format_search_result(result))]

    elif name == "simvault_validate_wire":
        src = load_port(arguments["src_subsystem_id"], arguments["src_port_canonical"])
        dst = load_port(arguments["dst_subsystem_id"], arguments["dst_port_canonical"])
        vr = validate_wire(src, dst)
        return [types.TextContent(type="text", text=vr.model_dump_json())]

    elif name == "simvault_get_assembly_context":
        ctx = get_assembly_context(arguments["subsystem_ids"])
        return [types.TextContent(type="text", text=ctx.model_dump_json())]

    elif name == "simvault_smoke_test":
        result = run_smoke_test(
            arguments["model_path"],
            arguments.get("rated_operating_point", {})
        )
        return [types.TextContent(type="text", text=result.model_dump_json())]

@app.list_tools()
async def list_tools():
    return [
        types.Tool(name="simvault_search", description="...", inputSchema={...}),
        types.Tool(name="simvault_validate_wire", description="...", inputSchema={...}),
        types.Tool(name="simvault_get_assembly_context", description="...", inputSchema={...}),
        types.Tool(name="simvault_smoke_test", description="...", inputSchema={...}),
    ]

if __name__ == "__main__":
    import asyncio
    asyncio.run(stdio_server(app))
```

**Registration** (add to `claude_desktop_config.json`):
```json
"simvault": {
  "command": "python",
  "args": ["-m", "simvault.mcp_server"],
  "cwd": "/path/to/SimVault"
}
```

**Done when:** `/mcp` in Claude Code shows `simvault` connected with 4 tools listed.

---

### Task 9 — CLI: `cli.py`
**File:** `simvault/cli.py`  
**Effort:** 1 hr  
**Depends on:** Tasks 5, 7

```python
import click

@click.group()
def cli(): pass

@cli.command()
@click.argument("model_dir")
def index(model_dir):
    """Index a directory of .slx files into SimVault."""
    run_matlab_extractor(model_dir)
    canonicalize_all("extracted/")
    build_graph("extracted/")
    build_index("extracted/")
    click.echo("Indexed successfully.")

@cli.command()
@click.argument("query_text")
@click.option("--fidelity", default=None)
@click.option("--analysis", default=None)
def query(query_text, fidelity, analysis):
    """Search SimVault for subsystems."""
    result = query_engine(query_text, fidelity_tier=fidelity, analysis_type=analysis)
    click.echo(format_result(result))

@cli.command()
@click.option("--src")
@click.option("--dst")
def validate(src, dst):
    """Validate a proposed wire between two ports."""
    ...
```

**Done when:** `simvault index ./examples/pmsm_drive && simvault query "PMSM thermal"` works end-to-end from the command line.

---

### Task 10 — Tests: `tests/`
**File:** `tests/test_integration.py`  
**Effort:** 2 hrs  
**Depends on:** Tasks 2–9

**Must pass before calling MVP complete:**

```python
def test_canonicalization_omega_rpm():
    """omega_shaft in RPM → canonical omega_shaft_rads with scale 0.1047"""
    port = {"original_name": "omega_rpm", "units": "rpm", "domain": "signal"}
    result = canonicalize_port(port)
    assert result["canonical_name"] == "omega_shaft_rads"
    assert abs(result["scale_factor"] - 0.1047) < 0.001

def test_validate_wire_domain_mismatch_blocks():
    """Simscape thermal port → Simulink signal must return BLOCK"""
    src = PortSpec(domain="thermal", direction="output", ...)
    dst = PortSpec(domain="signal",  direction="input",  ...)
    assert validate_wire(src, dst).result == "BLOCK"

def test_validate_wire_unit_mismatch_warns():
    """rad/s → rpm must return WARN with gain_factor=9.549"""
    src = PortSpec(canonical_units="rad/s", ...)
    dst = PortSpec(canonical_units="rpm",   ...)
    result = validate_wire(src, dst)
    assert result.result == "WARN"
    assert result.required_bridge_block.startswith("Gain")

def test_query_returns_compatible_partner():
    """Search for FEM PMSM returns thermal model as compatible partner"""
    result = query("high-fidelity PMSM", fidelity_tier="detailed")
    candidate_ids = [c["subsystem_id"] for c in result.candidates]
    all_node_ids = list(result.subgraph.nodes)
    assert any("PMSMMotor" in id for id in candidate_ids)
    assert any("Thermal" in id for id in all_node_ids)

def test_fidelity_filter_excludes_averaged():
    """Query with fidelity_tier=detailed must not return averaged motor"""
    result = query("PMSM motor", fidelity_tier="detailed")
    for c in result.candidates:
        assert c["fidelity_tier"] == "detailed"

def test_graph_has_fidelity_chain():
    """FEM motor and averaged motor must be linked by fidelity_chain edge"""
    G = load_graph("simvault.graph.json")
    edges = [(u,v,d) for u,v,d in G.edges(data=True) if d["type"] == "fidelity_chain"]
    assert len(edges) >= 1
```

---

## Build Order Summary

| Order | Task | File | Hrs | Gate |
|---|---|---|---|---|
| 1 | Scaffolding | pyproject.toml + dirs | 0.5 | pip install -e . |
| 2 | Parser | extract_metadata.m | 3.5 | Valid JSON from sample .slx |
| 3 | Canonicalizer | canonicalize.py | 2 | omega_rpm → omega_shaft_rads |
| 4 | Graph builder | build_graph.py | 3 | ≥1 compatible_with + fidelity_chain edge |
| 5 | Vector store | index.py | 1.5 | .svdb/ populated, query returns results |
| 6 | Validator | validate_ports.py | 2 | PASS/WARN/BLOCK on 3 test cases |
| 7 | Query engine | query.py | 3 | Thermal returned as compatible partner |
| 8 | MCP server | mcp_server.py | 2 | 4 tools visible in Claude Code /mcp |
| 9 | CLI | cli.py | 1 | simvault index + query works |
| 10 | Tests | tests/ | 2 | All 6 integration tests pass |
| **Total** | | | **~20.5 hrs** | |

---

## Phase 2 — Interactive Graph Visualizer

### Task 11 — Interactive two-level graph HTML (`graph_tree.html`)
**File:** `docs/graph_tree.html`  
**Effort:** 3–4 hrs  
**Depends on:** `simvault.graph.json` (Task 4)

**Design: Option C — two-level interactive**

Level 1 (default view) — model nodes only:
- 6 nodes, one per indexed model
- Node colour = `analysis_type` (thermal=orange, torque_accuracy=blue, drive_cycle=green, efficiency=teal)
- Node size = `block_count` (larger = more complex)
- Node label = model name + fidelity badge (detailed/simplified)
- Edges between models if they share ≥1 `compatible_with` port pair
- `fidelity_chain` edges rendered as dashed double-headed arrows with a distinct colour
- `requires_input_from` edges rendered as red dotted arrows

Level 2 (expand on click) — port nodes appear:
- Clicking a model node expands it into a cluster showing its port nodes as small satellites
- Port node colour = canonical name group (omega=purple, temperature=red, loss=orange, current=blue)
- Port node label = `canonical_name` (not original_name)
- `compatible_with` arcs appear between expanded port nodes of different models
- Clicking background collapses back to Level 1

**Implementation stack:** `vis-network` (CDN, no build step) reading `simvault.graph.json` directly via fetch.

**Generation:** Add `simvault graph` CLI command that writes `docs/graph_tree.html` from the current graph JSON.

**Done when:**
- Opening `graph_tree.html` in a browser shows 6 model nodes with correct edge types
- Clicking `MotorThermal11Node` expands to show `loss_copper_W` / `loss_iron_W` inputs and `temperature_K` outputs
- `compatible_with` arcs connect `MotorThermal11Node/loss_copper_W` to corresponding PMSM loss outputs
- `fidelity_chain` between `PMSM_FEM` and `PMSM_avg` is visible at Level 1

---

## Sample Models Needed for Examples

Use the following files from your existing agentic simulation work. Copy or symlink them into `examples/pmsm_drive/`. Do **not** create new models — these already exist at the paths shown.

| Source path | Copy to examples/ as | What it represents | Fidelity pair |
|---|---|---|---|
| `FEM_PMSM/test_PMSM_FEM_validation.slx` | `PMSM_FEM.slx` | FEM PMSM — high fidelity, Simscape physical ports | Pair A (high) |
| `FEM_PMSM/test_PMSM_FEM_avg_validation.slx` | `PMSM_avg.slx` | Averaged PMSM — same machine, lower fidelity | Pair A (low) |
| `MotorThermalModel/PMSMThermal11Node.slx` | `MotorThermal11Node.slx` | 11-node RC thermal model — copper/iron loss inputs | — |
| `FEM_PMSM/test_PMSM_FEM_foc.slx` | `FOCController.slx` | FOC controller — requires motor shaft + dq currents | — |
| `IMFluxMotorCADExample/IMFluxMotorCAD.slx` | `FEM_IM.slx` | Induction machine — different machine type | — |
| `MultiAgentWorkflow/models/FEM_IM_FOC_MA.slx` | `FEM_IM_FOC_MA.slx` | **Agent-built model** — the meta-test | — |

These 6 give coverage of every test case below. The PMSM_FEM / PMSM_avg pair is critical — it's the only way to validate fidelity_chain edge detection.

---

## Test Corpus — Pre-requisite Setup

Before indexing, add SimVault tags to each model's key subsystem Description field. Run this once in MATLAB:

```matlab
% simvault/examples/tag_models_for_simvault.m
% Run once before calling simvault index.

tags = {
  % {model_file,          subsystem_name,   fidelity_tier, analysis_type,   solver_contract}
  'PMSM_FEM',             'PMSM_FEM',       'detailed',    'torque_accuracy','continuous'
  'PMSM_avg',             'PMSM_FEM_avg',   'simplified',  'efficiency',     'continuous'
  'MotorThermal11Node',   'MotorThermalModel','detailed',   'thermal',        'continuous'
  'FOCController',        'FOCController',  'detailed',    'drive_cycle',    'continuous'
  'FEM_IM',               'FEM_IM',         'detailed',    'torque_accuracy','continuous'
  'FEM_IM_FOC_MA',        'FEM_IM_FOC',     'detailed',    'drive_cycle',    'continuous'
};

for i = 1:size(tags, 1)
    load_system(tags{i,1});
    block_path = [tags{i,1} '/' tags{i,2}];
    existing = get_param(block_path, 'Description');
    new_tag = sprintf('\nfidelity_tier: %s\nanalysis_type: %s\nsolver_contract: %s', ...
                      tags{i,3}, tags{i,4}, tags{i,5});
    if ~contains(existing, 'fidelity_tier')
        set_param(block_path, 'Description', [existing new_tag]);
        save_system(tags{i,1});
        fprintf('Tagged: %s/%s\n', tags{i,1}, tags{i,2});
    else
        fprintf('Already tagged: %s/%s\n', tags{i,1}, tags{i,2});
    end
    close_system(tags{i,1}, 0);
end
disp('Done.');
```

---

## Test Matrix — 9 Tests, One Per Capability

Run these after `simvault index examples/pmsm_drive/` completes.

| # | Command / Call | Expected result | Capability validated | Premortem # |
|---|---|---|---|---|
| **T1** | `simvault query "PMSM motor" --fidelity detailed` | `PMSM_FEM` returned, `PMSM_avg` NOT returned | Hard fidelity filter | #1 |
| **T2** | `simvault query "PMSM motor"` (no filter) | Both `PMSM_FEM` + `PMSM_avg` returned, linked by `fidelity_chain` edge | Fidelity chain graph edge | #1, #3 |
| **T3** | `simvault query "thermal model for PMSM"` (no filter) | `MotorThermal11Node` returned with `PMSM_FEM` as `compatible_with` partner | Cross-model graph expansion | #3 |
| **T4** | `simvault query "FOC" --analysis drive_cycle` | `FOCController` + `FEM_IM_FOC_MA` returned; `MotorThermal11Node` NOT returned | Analysis type hard filter | #6 |
| **T5** | `simvault validate --src "PMSM_FEM/omega_shaft_rads" --dst "MotorThermal11Node/temperature_K"` | **BLOCK**: domain mismatch (`rotational_mechanical` → `thermal`) | Domain mismatch detection | #2 |
| **T6** | `simvault validate --src "PMSM_FEM/omega_shaft_rads" --dst "FOCController/omega_shaft_rpm"` | **WARN**: Gain block required, factor `0.1047` | Unit mismatch with scale | #8 |
| **T7** | `simvault validate --src "PMSM_FEM/loss_copper_W" --dst "MotorThermal11Node/loss_copper_W"` | **PASS** | Validator happy path | #2, #7 |
| **T8** | Agent calls `simvault_search` + `simvault_get_assembly_context(["PMSM_FEM", "MotorThermal11Node"])` | Context has canonical port names, no BLOCK wires, solver = `ode15s` | Full agent query path | #7 |
| **T9** | `simvault index MultiAgentWorkflow/models/ && simvault query "induction motor FOC"` | `FEM_IM_FOC_MA` returned with correct tags | **Meta-test: agent-built models are reusable assets** | #4, #5 |

### T9 is the intent test

T9 validates SimVault's core purpose. The chain it proves:

```
Agent A (multi-agent workflow) → builds FEM_IM_FOC_MA.slx
SimVault                       → indexes it (hash check detects new file)
Agent B (future session)       → calls simvault_search("IM FOC drive cycle")
                               → retrieves FEM_IM_FOC_MA as a candidate
                               → calls simvault_get_assembly_context
                               → calls model_edit to build a new model
                                 reusing that subsystem
```

If T9 passes, agentic simulation work accumulates into a retrievable, reusable library — not one-off artifacts.

### Pass criteria summary

| Tests | All pass → | Meaning |
|---|---|---|
| T1, T4 | Hard filters work | Wrong-fidelity / wrong-domain models never returned |
| T2, T3 | Graph edges correct | Compatible and fidelity-chained models surface automatically |
| T5, T6, T7 | Validator correct | BLOCK / WARN / PASS all firing on right conditions |
| T8 | Agent path works | Claude can use SimVault to generate correct model_edit calls |
| T9 | Meta-test passes | The repo is self-reinforcing: each agentic build enriches the index |

---

## What to Do First on Saturday Morning

1. `cd SimVault && pip install -e .` — verify scaffolding (Task 1, 30 min)
2. Copy the 6 model files into `examples/pmsm_drive/`
3. Open MATLAB, run `tag_models_for_simvault.m` — adds SimVault Description tags
4. Run `extract_metadata('examples/pmsm_drive', 'extracted', 'simvault.lock.json')` — verify JSON output (Task 2)
5. Run `python -m simvault.canonicalizer.canonicalize extracted/` — verify port normalization (Task 3)
6. From there the dependency chain is linear: graph → vectors → validator → query → MCP → CLI → tests
7. After all tasks complete, run the T1–T9 test matrix to validate intent before calling it done

Do NOT start the MCP server (Task 8) until Tasks 5, 6, 7 pass their individual done-when criteria. The MCP server is a thin wrapper — if the underlying functions are wrong, the agent gets wrong answers through a harder-to-debug interface.
