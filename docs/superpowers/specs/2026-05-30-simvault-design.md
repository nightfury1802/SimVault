# SimVault — Design Specification
**Version:** 1.0  
**Date:** 2026-05-30  
**Status:** Approved for implementation

---

## 1. Problem Statement

MATLAB/Simulink simulation repositories grow into hundreds of `.slx` models — motors, inverters, gearboxes, thermal models, FOC controllers — built by different engineers at different fidelity levels for different analysis types. Finding the right subsystem, understanding what it can connect to, and assembling a new model from existing components requires manual expertise that takes hours and produces errors that don't surface until weeks later.

Simulink Copilot (MathWorks R2026a) works on one open model at a time. It cannot search across a library, retrieve a subsystem from model A to use in model B, or reason about physical port compatibility across models.

SimVault is a physics-aware GraphRAG system for MATLAB/Simulink model libraries. It indexes `.slx` models into a graph of physically-typed subsystems, enables semantic search filtered by fidelity and analysis type, and validates assembly candidates before an LLM generates connection code — making the assembly errors identified in the premortem analysis structurally impossible.

---

## 2. Scope

### In scope (v1)
| File type | Purpose |
|---|---|
| `.slx` | Simulink/Simscape model files — primary target |
| `.m` | MATLAB scripts that configure or parameterize models (PreLoadFcn, build scripts) |
| `.mat` | Parameter data files (flux maps, CRT tables, thermal constants) |

### Out of scope (v1, explicitly excluded)
- `.jl` Julia files — handled by personal kb/graphify
- `.ame` AMESim files — no public parsing API; Phase 3 candidate
- `.mlx` MATLAB Live Scripts — Phase 2
- `.sldd` Simulink Data Dictionaries — Phase 2
- Any non-MATLAB/Simulink file

### Relationship to personal kb
SimVault is a **standalone GitHub project**. It does not depend on, write to, or read from the personal kb/graphify+turbovec stack. An optional one-way bridge (`bridge/kb_export.py`) can generate plain-language markdown summaries that a personal kb can optionally import. The bridge is never a dependency.

---

## 3. Architecture

```
SimVault Repository
├── simvault/
│   ├── parser/
│   │   └── extract_metadata.m        ← MATLAB: crawl .slx, extract JSON
│   ├── canonicalizer/
│   │   └── canonicalize.py           ← normalize port names + units
│   ├── graph/
│   │   ├── build_graph.py            ← construct SimVault graph
│   │   └── simvault.graph.json       ← persisted graph (NetworkX schema)
│   ├── vectors/
│   │   ├── index.py                  ← ChromaDB indexer
│   │   └── .svdb/                    ← ChromaDB persistent store
│   ├── validator/
│   │   └── validate_ports.py         ← deterministic assembly gate
│   ├── query/
│   │   └── query.py                  ← GraphRAG query engine
│   ├── bridge/
│   │   └── kb_export.py              ← optional: markdown for personal kb
│   └── cli.py                        ← simvault index | query | assemble
├── hooks/
│   └── post-commit                   ← git hook: auto re-index on .slx change
├── examples/
│   └── pmsm_drive/                   ← sample .slx files for demo
├── tests/
└── simvault.lock.json                ← SHA hash registry
```

---

## 4. Component Specifications

### 4.1 Parser — `extract_metadata.m`

MATLAB batch script. Requires no Simulink Agentic Toolkit at runtime — uses standard `load_system` / `find_system` / `get_param` API so it works with any MATLAB + Simulink installation.

**Crawl logic:**
- Recursively finds all `.slx` in the target directory
- Skips `slprj/`, hidden folders, `_archive/`
- Computes SHA-256 hash of each `.slx` file
- Skips re-extraction if hash matches `simvault.lock.json`

**Extracted fields per subsystem:**

```json
{
  "identity": {
    "model_file": "PMSMThermal.slx",
    "subsystem_path": "PMSMThermal/MotorThermalModel",
    "subsystem_name": "MotorThermalModel",
    "description": "11-node RC thermal network for IPMSM stator/rotor/housing"
  },
  "tags": {
    "fidelity_tier": "detailed",
    "analysis_type": "thermal",
    "solver_contract": "continuous"
  },
  "solver": {
    "type": "variable",
    "name": "ode15s",
    "sample_time": "-1",
    "stop_time": "300"
  },
  "ports": [
    {
      "original_name": "Q_copper",
      "direction": "input",
      "port_type": "physical",
      "domain": "thermal",
      "units": "W",
      "description": "Copper loss heat input"
    },
    {
      "original_name": "T_winding",
      "direction": "output",
      "port_type": "physical",
      "domain": "thermal",
      "units": "K",
      "description": "Winding temperature"
    }
  ],
  "block_count": 47,
  "state_count": 11,
  "source_hash": "a3f9c2...",
  "extracted_at": "2026-05-30T14:23:00Z"
}
```

**Tag resolution order:**
1. Read structured tags from the subsystem `Description` field  
   (`fidelity_tier: detailed`, `analysis_type: thermal`, `solver_contract: continuous`)
2. If missing, infer `fidelity_tier` from block count heuristic (< 10 = simplified, 10–50 = lookup, > 50 = detailed)
3. If missing, infer `solver_contract` from solver name (ode45/ode15s = continuous, FixedStepDiscrete = discrete)
4. `analysis_type` must always be explicit — never inferred; flag as `"untagged"` if absent

**Output:** `extracted/<model_name>.json` per model

---

### 4.2 Canonicalizer — `canonicalize.py`

Reads extracted JSON, normalizes port names and units, writes canonicalized JSON + markdown spec.

**Canonical port name table:**

| Pattern matched | Canonical name | Canonical unit | Scale factor if needed |
|---|---|---|---|
| `omega`, `speed`, `w_out`, `w`, `rpm`, `n_shaft` | `omega_shaft_rads` | rad/s | if `rpm` detected: ×(2π/60) |
| `torque`, `trq`, `T`, `t_out`, `tau` | `torque_shaft_Nm` | N·m | — |
| `T_winding`, `temp`, `temperature`, `t_pm`, `T_stator` | `temperature_K` | K | if °C detected: +273.15 |
| `id`, `Id`, `i_d` | `id_current_A` | A | — |
| `iq`, `Iq`, `i_q` | `iq_current_A` | A | — |
| `Vdc`, `v_dc`, `VDC`, `DC_voltage` | `vdc_V` | V | — |
| `Q_copper`, `P_copper`, `Pcu` | `loss_copper_W` | W | — |
| `Q_iron`, `P_iron`, `Pfe` | `loss_iron_W` | W | — |
| `flux_d`, `lambda_d`, `psi_d` | `flux_d_Wb` | Wb | — |
| `flux_q`, `lambda_q`, `psi_q` | `flux_q_Wb` | Wb | — |

**Unit mismatch detection:**
- If original name contains `rpm` or `RPM`: flag `UNIT_MISMATCH`, emit required gain factor
- If original name ends in `_degC` or `_C`: flag `UNIT_OFFSET`, emit required offset

**Markdown spec output** (`kb/models/<model>_<subsystem>.md`):

```markdown
---
fidelity_tier: detailed
analysis_type: thermal
solver_contract: continuous
source_file: PMSMThermal.slx
source_hash: a3f9c2...
block_count: 47
state_count: 11
---

## MotorThermalModel

11-node RC thermal network for IPMSM. Accepts copper and iron loss inputs
as heat sources (W). Outputs winding, magnet, and housing temperatures (K).
Suitable for continuous-time drive cycle and efficiency analysis.

### Port Interface

| Canonical Name     | Original Name | Direction | Domain  | Units | Status      |
|--------------------|---------------|-----------|---------|-------|-------------|
| loss_copper_W      | Q_copper      | input     | thermal | W     | ✓ canonical |
| loss_iron_W        | Q_iron        | input     | thermal | W     | ✓ canonical |
| temperature_K      | T_winding     | output    | thermal | K     | ✓ canonical |

### Compatibility Alerts
> ⚠ Requires `loss_iron_W` driver from EM model. Averaged EM models have no
> iron loss output — thermal iron loss node will remain at ambient if
> connected to an averaged motor.
```

---

### 4.3 Graph Builder — `build_graph.py`

Constructs `simvault.graph.json` — a NetworkX node-link graph with SimVault-specific edge types. This is **not** a text co-occurrence graph. Every edge encodes a physical or structural relationship derivable from the extracted metadata.

**Node types:**

```
SubsystemNode
  id: "<model_file>/<subsystem_path>"
  type: "subsystem"
  fidelity_tier: simplified | lookup | detailed | fem | surrogate
  analysis_type: efficiency | drive_cycle | torque_accuracy | thermal | ...
  solver_contract: continuous | discrete | steady_state
  block_count: int
  state_count: int
  source_hash: str

PortNode
  id: "<subsystem_id>/ports/<canonical_name>"
  type: "port"
  direction: input | output | bidirectional
  domain: thermal | rotational_mechanical | electrical | signal | ...
  units: str
  canonical_name: str
```

**Edge types:**

| Edge type | Source → Target | Meaning | How derived |
|---|---|---|---|
| `has_port` | SubsystemNode → PortNode | subsystem exposes this port | extracted metadata |
| `physically_connects_to` | PortNode → PortNode | actually wired in the source model | parsed from model connections |
| `compatible_with` | PortNode → PortNode | can be legally connected (same domain + compatible units) | computed by canonicalizer |
| `fidelity_chain` | SubsystemNode → SubsystemNode | same component at lower fidelity | matched by subsystem name stem + description similarity |
| `analysis_context_match` | SubsystemNode → SubsystemNode | same analysis_type + solver_contract | computed from tags |
| `requires_input_from` | SubsystemNode → SubsystemNode | subsystem B has an unconnected input port that subsystem A provides | derived from unconnected ports + compatible_with |

**`compatible_with` rule:**
Two ports are `compatible_with` if and only if:
1. Their `domain` values are identical
2. Their canonical units are the same OR a known scale factor exists between them
3. They have opposite directions (one input, one output) OR both bidirectional
4. Their parent subsystems have compatible `solver_contract` values

**`fidelity_chain` detection:**
Two subsystems are in a fidelity chain if:
1. The subsystem name stem matches after stripping these exact suffixes (case-insensitive): `_fem`, `_avg`, `_averaged`, `_lookup`, `_lut`, `_surrogate`, `_nn`, `_simplified`, `_detailed`, `_highfidelity`, `_hifi`, `_reduced`
2. OR the `description` fields share > 0.85 cosine similarity AND they share the same `analysis_type`
3. AND they have different `fidelity_tier` values — same tier never chains to itself

---

### 4.4 Vector Store — `index.py` + ChromaDB

**Why ChromaDB:** Open source, runs locally with zero server setup, supports metadata filtering as a first-class operation, persistent across sessions, no license restrictions for a public GitHub repo.

**Collection schema:**

```python
collection.add(
    ids=["PMSMThermal/MotorThermalModel"],
    documents=["11-node RC thermal network for IPMSM. Accepts copper and iron loss..."],
    metadatas=[{
        "fidelity_tier": "detailed",
        "analysis_type": "thermal",
        "solver_contract": "continuous",
        "source_file": "PMSMThermal.slx",
        "source_hash": "a3f9c2...",
        "block_count": 47,
        "state_count": 11,
        "has_iron_loss_input": True,
        "has_copper_loss_input": True,
        "output_domains": "thermal",
        "input_domains": "thermal"
    }]
)
```

**Embedding model:** `BAAI/bge-small-en-v1.5` (matches Gemini plan, lightweight, runs locally, good domain adaptation)

**What gets embedded:** The markdown causal behavior summary (not the raw JSON, not the port table). The summary is written to emphasize physics purpose, not implementation details.

---

### 4.5 Validator — `validate_ports.py`

Deterministic gate called **before** any `model_edit` call. Takes a proposed wire as input, returns `PASS`, `WARN`, or `BLOCK`.

**Checks in order:**

```python
def validate_wire(src_port: PortSpec, dst_port: PortSpec) -> ValidationResult:
    # 1. Domain match (BLOCK on failure — no override)
    if src_port.domain != dst_port.domain:
        return BLOCK("domain_mismatch", src=src_port.domain, dst=dst_port.domain)

    # 2. Direction compatibility (BLOCK on failure)
    if not directions_compatible(src_port.direction, dst_port.direction):
        return BLOCK("direction_conflict")

    # 3. Unit match (WARN with required gain, never silent)
    if src_port.units != dst_port.units:
        factor = UNIT_CONVERSION_TABLE.get((src_port.units, dst_port.units))
        if factor is None:
            return BLOCK("unit_incompatible", src=src_port.units, dst=dst_port.units)
        return WARN("unit_scale_required", gain_block=factor)

    # 4. Solver contract (WARN with required bridge block)
    if src_port.solver_contract != dst_port.solver_contract:
        return WARN("solver_mismatch",
                    fix="insert Rate Transition block between continuous and discrete subsystems")

    return PASS()
```

**Post-assembly smoke test** (called after every LLM assembly):
1. Check all thermal loss input ports have nonzero driver signals at rated operating point
2. Verify `state_count` after `structural_simplify` ≥ sum of component state counts
3. Run 1-second trim at rated operating point; flag any signals identically zero where physics predicts nonzero

---

### 4.6 Query Engine — `query.py`

The GraphRAG query flow. This is what separates SimVault from generic semantic search.

```
query(text, fidelity_tier=None, analysis_type=None, solver_contract=None)
    │
    ▼
Step 1: HARD FILTER (ChromaDB where clause)
    Filter on fidelity_tier, analysis_type, solver_contract before any embedding comparison.
    A drive_cycle subsystem never competes with an efficiency subsystem regardless of
    cosine similarity. These are not ranking signals — they are gates.
    │
    ▼
Step 2: SEMANTIC SEARCH (ChromaDB query)
    Embed the query text. Retrieve top-5 subsystem candidates from the filtered set.
    Return: list of SubsystemNode ids with similarity scores.
    │
    ▼
Step 3: GRAPH EXPANSION (simvault.graph.json traversal)
    For each seed node:
      - Traverse `compatible_with` edges to find port-compatible partners
      - Traverse `fidelity_chain` edges to surface lower/higher fidelity alternatives
      - Traverse `requires_input_from` edges to identify mandatory companions
      - Traverse `analysis_context_match` edges to find co-validated combinations
    Return: expanded subgraph (typically 5-12 nodes)
    │
    ▼
Step 4: VALIDATE CANDIDATES (validate_ports.py)
    For every edge in the expanded subgraph that represents a proposed assembly wire:
      - Run validate_wire() on each port pair
      - Remove BLOCK-level pairs from the candidate set
      - Annotate WARN-level pairs with required bridge blocks
    Return: validated assembly candidate set
    │
    ▼
Step 5: CONTEXT ASSEMBLY
    Package the validated subgraph into a structured context for the LLM:
      - Canonical port names (not original names)
      - Port domain + unit specs
      - Required bridge blocks (Rate Transition, gain blocks)
      - Fidelity chain alternatives
    The LLM never sees ambiguous port names. It receives exact canonical names
    that match what model_edit expects.
```

---

## 5. Premortem Mitigations — Traceability Matrix

| # | Failure mode | Mitigation | Component |
|---|---|---|---|
| 1 | Embedding collapse — FEM vs averaged identical vectors | fidelity_tier as hard ChromaDB filter, never a ranking signal | 4.4 Vector Store |
| 2 | Port domain mismatch — Simscape HeatPort wired to double | domain field mandatory in PortNode; validate_wire() BLOCKS on domain mismatch | 4.3 Graph, 4.5 Validator |
| 3 | Fidelity mismatch — iron loss port unconnected | `requires_input_from` edge surfaced in graph expansion; compatibility alert in markdown spec | 4.3 Graph, 4.2 Canonicalizer |
| 4 | Parameter drift — stale index returns old flux maps | SHA-256 hash per .slx in `simvault.lock.json`; re-index triggered on hash change | 4.1 Parser |
| 5 | Maintenance burden — shelfware in 3 months | `hooks/post-commit` git hook; re-indexing runs automatically on every .slx commit | hooks/ |
| 6 | Case-type metadata lost — steady-state + transient mixed | analysis_type hard filter; solver_contract hard filter; validate_wire() WARNS on solver mismatch | 4.4, 4.5 |
| 7 | LLM assembly hallucination — Id/Iq swapped, ratio inverted | LLM receives canonical names only; post-assembly smoke test detects zero copper/iron loss | 4.2, 4.5 |
| 8 | Naming convention chaos — omega_shaft vs shaft_speed_rpm | Canonicalization table maps all variants to canonical names before indexing | 4.2 Canonicalizer |

---

## 6. Data Contracts

### `simvault.lock.json`
```json
{
  "version": "1.0",
  "last_indexed": "2026-05-30T14:23:00Z",
  "files": {
    "PMSMThermal.slx": {
      "hash": "a3f9c2...",
      "indexed_at": "2026-05-30T14:23:00Z",
      "subsystems": ["MotorThermalModel", "InverterThermal"]
    }
  }
}
```

### `simvault.graph.json` (NetworkX node-link format)
```json
{
  "directed": true,
  "multigraph": false,
  "nodes": [
    {
      "id": "PMSMThermal.slx/MotorThermalModel",
      "type": "subsystem",
      "fidelity_tier": "detailed",
      "analysis_type": "thermal",
      "solver_contract": "continuous",
      "block_count": 47,
      "state_count": 11
    },
    {
      "id": "PMSMThermal.slx/MotorThermalModel/ports/loss_copper_W",
      "type": "port",
      "direction": "input",
      "domain": "thermal",
      "units": "W"
    }
  ],
  "links": [
    {
      "source": "PMSMThermal.slx/MotorThermalModel",
      "target": "PMSMThermal.slx/MotorThermalModel/ports/loss_copper_W",
      "type": "has_port"
    },
    {
      "source": "PMSMMotor.slx/PMSMMotor_FEM/ports/loss_copper_W",
      "target": "PMSMThermal.slx/MotorThermalModel/ports/loss_copper_W",
      "type": "compatible_with"
    }
  ]
}
```

---

## 7. Agent Interface — MCP Server

SimVault exposes itself as an MCP server (`simvault/mcp_server.py`) so that Claude Code or any MCP-capable agent can call it directly alongside the existing simulink MCP. The agent never touches the CLI — it calls MCP tools.

### Tool definitions

**`simvault_search`**
```json
{
  "name": "simvault_search",
  "description": "Search SimVault for subsystems matching a query. Hard filters on fidelity_tier and analysis_type are applied before semantic ranking. Returns subsystem candidates plus their graph-expanded compatible partners.",
  "input_schema": {
    "query": "string — natural language description of what you need",
    "fidelity_tier": "string? — simplified | lookup | detailed | fem | surrogate",
    "analysis_type": "string? — efficiency | drive_cycle | torque_accuracy | thermal | ...",
    "solver_contract": "string? — continuous | discrete | steady_state",
    "top_k": "integer? — default 5"
  },
  "output": {
    "candidates": [
      {
        "subsystem_id": "PMSMMotor.slx/PMSMMotor_FEM",
        "similarity_score": 0.94,
        "fidelity_tier": "detailed",
        "analysis_type": "efficiency",
        "compatible_partners": ["PMSMThermal.slx/MotorThermalModel"],
        "fidelity_alternatives": ["PMSMMotor.slx/PMSMMotor_averaged"],
        "ports": [...]
      }
    ]
  }
}
```

**`simvault_validate_wire`**
```json
{
  "name": "simvault_validate_wire",
  "description": "Validate a proposed wire between two subsystem ports before calling model_edit. Returns PASS, WARN (with required bridge block), or BLOCK (with reason). Always call this before model_edit for any cross-subsystem connection.",
  "input_schema": {
    "src_subsystem_id": "string",
    "src_port_canonical": "string",
    "dst_subsystem_id": "string",
    "dst_port_canonical": "string"
  },
  "output": {
    "result": "PASS | WARN | BLOCK",
    "reason": "string?",
    "required_bridge_block": "string? — e.g. 'Rate Transition' or 'Gain (factor: 0.1047)'",
    "gain_factor": "number?"
  }
}
```

**`simvault_get_assembly_context`**
```json
{
  "name": "simvault_get_assembly_context",
  "description": "Given a list of subsystem IDs to assemble, returns the full structured context needed to generate model_edit calls: canonical port names, validated wire list, required bridge blocks, and solver configuration. Use this after simvault_search to get the exact information model_edit needs.",
  "input_schema": {
    "subsystem_ids": ["string"]
  },
  "output": {
    "canonical_wires": [
      {
        "src": "PMSMMotor.slx/PMSMMotor_FEM/ports/loss_copper_W",
        "dst": "PMSMThermal.slx/MotorThermalModel/ports/loss_copper_W",
        "validation": "PASS"
      }
    ],
    "bridge_blocks_required": [...],
    "solver_recommendation": "ode15s, variable-step, continuous",
    "assembly_warnings": [...]
  }
}
```

**`simvault_smoke_test`**
```json
{
  "name": "simvault_smoke_test",
  "description": "Run post-assembly validation on a newly built model. Checks for unconnected thermal loss ports, zero signals at rated operating point, and state count consistency. Call after model_edit assembly is complete.",
  "input_schema": {
    "model_path": "string — path to the assembled .slx file",
    "rated_operating_point": {
      "speed_rads": "number",
      "torque_Nm": "number"
    }
  },
  "output": {
    "pass": "boolean",
    "checks": [
      {"name": "thermal_loss_ports_connected", "result": "PASS | FAIL", "detail": "string"},
      {"name": "state_count_consistent", "result": "PASS | FAIL", "detail": "string"},
      {"name": "no_zero_physics_signals", "result": "PASS | FAIL", "detail": "string"}
    ]
  }
}
```

### Agent workflow (end-to-end)

```
User: "Build a 150kW efficiency analysis model with high-fidelity PMSM and thermal"
    │
    ├─ simvault_search(
    │    query="high-fidelity PMSM motor",
    │    fidelity_tier="detailed",
    │    analysis_type="efficiency"
    │  )
    │  → returns PMSMMotor_FEM + compatible partner MotorThermalModel
    │
    ├─ simvault_search(
    │    query="thermal model for PMSM efficiency",
    │    fidelity_tier="detailed",
    │    analysis_type="efficiency"
    │  )
    │  → confirms MotorThermalModel, surfaces fidelity alternative: MotorThermal_3node
    │
    ├─ simvault_get_assembly_context(
    │    subsystem_ids=["PMSMMotor.slx/PMSMMotor_FEM",
    │                   "PMSMThermal.slx/MotorThermalModel"]
    │  )
    │  → returns canonical wires, validated connections, solver recommendation
    │
    ├─ simulink_mcp.model_edit(...)   ← uses exact canonical port names from context
    │  [LLM generates model_edit calls from structured context — no port name guessing]
    │
    └─ simvault_smoke_test(
         model_path="assembled_150kW_efficiency.slx",
         rated_operating_point={speed_rads: 314, torque_Nm: 477}
       )
       → PASS / FAIL with specific check details
```

### MCP server registration

SimVault MCP server runs locally on stdio, same pattern as the existing simulink MCP:

```json
{
  "mcpServers": {
    "simvault": {
      "command": "python",
      "args": ["-m", "simvault.mcp_server"],
      "cwd": "/path/to/SimVault"
    }
  }
}
```

---

## 8. CLI Interface (Human Use)

```bash
# Index a model library
simvault index ./models/

# Query — returns validated assembly candidates
simvault query "high-fidelity PMSM with thermal for efficiency analysis" \
  --fidelity detailed \
  --analysis efficiency

# Validate a proposed wire before model_edit
simvault validate \
  --src "PMSMMotor.slx/PMSMMotor_FEM/loss_copper_W" \
  --dst "PMSMThermal.slx/MotorThermalModel/loss_copper_W"

# Inspect graph neighbourhood of a subsystem
simvault graph "PMSMThermal.slx/MotorThermalModel" --depth 2

# Export summaries for personal kb integration (optional)
simvault export --format kb-markdown --output ./kb/models/
```

---

## 8. Phase Breakdown

### Phase 1 — Weekend MVP (buildable in 2 days)

| Component | File | Effort | Notes |
|---|---|---|---|
| Parser | `extract_metadata.m` | 3–4 hrs | |
| Canonicalizer | `canonicalize.py` | 2 hrs | |
| Graph builder | `build_graph.py` | 3 hrs | |
| ChromaDB indexer | `index.py` | 1 hr | |
| Validator (domain + direction + unit checks only) | `validate_ports.py` | 2 hrs | Post-assembly smoke test is Phase 2 |
| Query engine (all 5 steps) | `query.py` | 3 hrs | Step 4 uses Phase 1 validator |
| MCP server (4 tools) | `mcp_server.py` | 2 hrs | Exposes search, validate, context, smoke_test |
| Basic CLI | `cli.py` | 1 hr | Thin wrapper over same core functions |
| Tests on sample .slx | `tests/` | 2 hrs | |

**Onboarding note:** `analysis_type` is never inferred — it must be set in each subsystem's Simulink `Description` field (`analysis_type: efficiency`). Models without this tag are indexed as `"untagged"` and excluded from filtered queries. A one-time tagging pass on your model library is required before Phase 1 queries are useful. Budget 1–2 hours for a library of ~20 models.

**MVP success criterion:** Given 5 sample `.slx` files (motor, thermal, FOC, gearbox, inverter), the query `"detailed thermal model compatible with PMSM for efficiency"` returns `MotorThermalModel` as the top result, with `PMSMMotor_FEM` surfaced as its compatible partner via graph expansion — and `validate_ports.py` confirms the copper loss wire is PASS.

### Phase 2 — Post-weekend

- Post-assembly smoke test added to `validate_ports.py`
- `hooks/post-commit` git hook for auto re-indexing on `.slx` changes
- `.m` and `.mat` file indexing
- `kb_export.py` optional one-way bridge to personal kb
- Full CLI with `assemble` subcommand (wraps query → validate → model_edit)

### Phase 3 — GitHub polish

- D3.js fidelity dashboard (port from Gemini's plan)
- Auto-learning oracle feedback loop
- PyPI package (`pip install simvault`)
- README with demo GIF using sample PMSM drive models
- GitHub Actions CI for tests

---

## 9. Dependencies

```toml
# Python
chromadb = ">=0.4"
sentence-transformers = ">=2.2"   # BAAI/bge-small-en-v1.5
networkx = ">=3.0"
click = ">=8.0"                   # CLI
numpy = ">=1.24"

# MATLAB (runtime, not a Python dep)
# Requires MATLAB R2023b+ with Simulink
# No additional toolboxes required for extract_metadata.m
```

---

## 10. What SimVault Does That Simulink Copilot Cannot

| Capability | Simulink Copilot (R2026a) | SimVault |
|---|---|---|
| Search across model library | No — one open model | Yes |
| Retrieve subsystem from model A, use in model B | No | Yes |
| Fidelity-tier hard filtering | No | Yes |
| Physical port domain compatibility checking | No | Yes |
| Cross-model graph traversal | No | Yes |
| Assembly validation before model_edit | No | Yes |
| Open source, no MathWorks license required | No | Yes |
| Works with any MATLAB R2023b+ installation | N/A (requires Copilot license) | Yes |
| Optional bridge to personal kb | No | Yes |

---

*Spec written by Claude Sonnet 4.6 in collaboration with the SimVault author.*  
*Premortem: `SimVault/premortem-report-20260529.html`*  
*Transcript: `SimVault/premortem-transcript-20260529.md`*
