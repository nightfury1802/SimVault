# SimVault

**A unified knowledge graph and semantic search engine for Simscape/Simulink model libraries — built so AI agents can assemble physically-valid models without hallucinating wires.**

---

## The Problem

Every Simscape modeling session produces `.slx` files that no future agent can find or reuse. Port names are inconsistent (`omega_rpm` vs `w_shaft` vs `SpeedPS`). Domain mismatches (thermal port → signal line) cause silent errors. Fidelity variants (FEM ↔ averaged) are invisible to a search engine. The result: every agent rebuilds from scratch, makes the same wiring mistakes, and produces one-off artifacts that never compound.

## What SimVault Does

SimVault indexes a directory of `.slx` files into a **combined vector + graph store**. When an agent needs to build a new model, it calls SimVault first:

```
simvault_search("PMSM thermal model, high-fidelity, continuous")
    → returns MotorThermal11Node + PMSM_FEM as compatible partners

simvault_get_assembly_context(["PMSM_FEM", "MotorThermal11Node"])
    → returns canonical port names, solver info, pre-validated wires

simulink_mcp.model_edit(...)
    → builds the model using SimVault's context — no guessing
```

Each agentic build enriches the index. Over time, the library self-reinforces.

---

## Architecture

```
.slx files
    │
    ▼
extract_metadata.m          ← MATLAB: SHA-256 lock, SL2PS/PS2SL port detection
    │
    ▼
canonicalize.py             ← omega_rpm → omega_shaft_rads, loss_iron_W, etc.
    │
    ├──► build_graph.py     ← NetworkX: compatible_with / fidelity_chain / has_port
    │
    └──► vectors/index.py   ← turbovec IdMapIndex, BAAI/bge-small-en-v1.5, 4-bit
              +
         knowledge/indexer.py  ← same index: graphify KB chunks (session logs, pitfalls)
              │
         graph/link_entities.py  ← cross_edges.json: KB nodes → SimVault models
              │
         retrieval/unified.py    ← semantic + BM25 + cross-edges, fused by RRF
              │
         mcp_server.py  ─── ← 6 MCP tools for Claude agents
         cli.py              ← 8 CLI commands
```

### Dual-graph design

SimVault maintains two graphs that share a single embedding index:

| Graph | File | Size | Content |
|---|---|---|---|
| **Model Graph** | `simvault.graph.json` | 28 subsystems · 129 ports · 1541 edges | Port-level structure and compatibility of `.slx` subsystems |
| **KB Knowledge Graph** | `graphify-out/graph.json` | 8228 nodes · 16795 edges | Session logs, code, pitfalls, validated results from graphify |

**Cross-edges** (`store/cross_edges.json`, 358 edges) link KB nodes that mention a model ID to the corresponding SimVault model node — bridging history and structure in a single query.

---

## Quick Start

```bash
git clone https://github.com/nightfury1802/SimVault.git
cd SimVault
pip install -e .

# 1. Tag your models (run once in MATLAB R2024a+)
matlab -batch "run('examples/tag_models_for_simvault.m')"

# 2. Index .slx files
simvault index examples/pmsm_drive/

# 3. Semantic search
simvault query "PMSM thermal model" --fidelity detailed

# 4. Validate a proposed wire
simvault validate \
  --src "PMSM_FEM/omega_shaft_rads" \
  --dst "FOCController/omega_shaft_rads"

# 5. Query KB history (session logs, pitfalls, validated results)
simvault kb-query "FEM_IM torque ripple root cause"
```

---

## MCP Tools

Register in `claude_desktop_config.json`:

```json
"simvault": {
  "command": "python",
  "args": ["-m", "simvault.mcp_server"],
  "cwd": "/path/to/SimVault",
  "env": {
    "SIMVAULT_ROOT": "/path/to/SimVault"
  }
}
```

| Tool | What it does |
|---|---|
| `simvault_search` | Semantic search with hard fidelity/analysis/solver filters |
| `simvault_validate_wire` | PASS / WARN / BLOCK on a proposed port connection |
| `simvault_get_assembly_context` | Full port table + validated wire pairs for a set of subsystems |
| `simvault_smoke_test` | Load check + optional 0.1s simulation at rated operating point |
| `simvault_kb_query` | Unified KB search: semantic + BM25 + graph, fused with RRF |
| `simvault_model_context_with_history` | Assembly context + KB session history in one call |

---

## CLI Commands

| Command | Description |
|---|---|
| `simvault index <dir>` | Full index pipeline: MATLAB → canonicalize → graph → embed. `--skip-matlab` to skip extraction. |
| `simvault query <text>` | Semantic search with optional `--fidelity`, `--analysis`, `--solver` filters |
| `simvault validate --src --dst` | Validate a proposed wire (format: `SubsystemId/port_canonical_name`) |
| `simvault context <id1> [id2...]` | Get full assembly context JSON for a set of subsystems |
| `simvault kb-update` | Full KB pipeline: export → LLM extract → graphify → cross-edges → embed → viz |
| `simvault kb-query <text>` | Unified KB search (semantic + BM25 + graph, RRF-fused) |
| `simvault kb-extract-session [N]` | List sessions or extract LLM facts from session N |
| `simvault viz [--open]` | Regenerate HTML visualizations (model graph + KB sync) |

---

## KB Pipeline (`simvault kb-update`)

Runs automatically via the Claude Code Stop hook at the end of every session. Six stages:

1. **Export** — reads lean-ctx knowledge atoms → `store/sessions/YYYY-MM-DD.md`
2. **LLM extract** — `claude-haiku-4-5-20251001` extracts 5–15 structured facts (pitfall / result / decision / model_ref) from the latest session transcript
3. **Graphify update** — rebuilds `graphify-out/graph.json` from all source files
4. **Cross-edge linking** — scans KB graph for model ID mentions → `store/cross_edges.json`
5. **Knowledge indexing** — embeds new graphify cache chunks into `store/kb.tq` (incremental, mtime-based)
6. **Visualization** — regenerates `docs/model_graph.html` and syncs KB visuals

---

## Unified Query Engine

`simvault_kb_query` and `simvault kb-query` route through three retrieval strategies, then fuse with **Reciprocal Rank Fusion (RRF)**:

| Query type | Detected by | Strategy |
|---|---|---|
| `relationship` | Keywords: connect, path, between, depends on, upstream… | graphify BFS traversal |
| `model+kb` | Known model ID in query (PMSM_FEM, FEM_IM, …) | Semantic + BM25 + cross-edges |
| `kb` | Default | Semantic + BM25 |

**Confidence decay** is applied after fusion: episodic facts (session logs) decay linearly over 90 days; procedural facts (model specs, source code) are permanent. Superseded or expired facts score 0.

---

## Memory Tiers

| Tier | Decay | Assigned to |
|---|---|---|
| `working` | 7 days | Raw session observations |
| `episodic` | 90 days | graphify cache chunks, session MD exports |
| `semantic` | Permanent | PLAN.md decisions, validated facts |
| `procedural` | Permanent | Model specs, MATLAB/Python source, skills |

---

## Wire Validator

Four rules applied in order:

| Rule | Outcome | Example |
|---|---|---|
| Domain mismatch (physical ↔ signal) | **BLOCK** | Simscape port wired to Simulink signal |
| Direction conflict (output → output) | **BLOCK** | Two output ports connected |
| Unit mismatch with known conversion | **WARN** + Gain block | rpm → rad/s (factor: 0.10472) |
| Solver contract mismatch | **WARN** + bridge block | continuous ↔ discrete → Rate Transition |

---

## Canonical Port Names

The canonicalizer maps 20+ raw naming patterns to a fixed vocabulary:

| Canonical name | Matches | Units |
|---|---|---|
| `omega_shaft_rads` | omega, speed, w_shaft, SpeedPS, wr, speed_ref, speed_cmd | rad/s |
| `torque_shaft_Nm` | torque, TPS, trq, tau, torque_ref | N·m |
| `temperature_K` | temp, AirGap, Frame, Magnets, Shaft, winding_K, vector_K, TPS_Core… | K |
| `loss_copper_W` | Copper_Loss, End_Winding_Copper, Side_Winding_Copper, Pcu | W |
| `loss_iron_W` | Rotor_Iron_Loss, Stator_Teeth_Loss, Magnet_Eddy, Pfe | W |
| `id_current_A` | id, i_d, isd, i_sd, id_ref | A |
| `iq_current_A` | iq, i_q, isq, i_sq, iq_ref | A |
| `iabc_A` | iabc, i_abc, ia_A, ib_A, ic_A | A |
| `vabc_V` | vabc, v_abc | V |
| `vdc_V` | Vdc, v_dc, DC_voltage | V |
| `flux_d_Wb` | flux_d, lambda_d, psi_d | Wb |
| `flux_q_Wb` | flux_q, lambda_q, psi_q | Wb |
| `field_angle_rad` | field_angle, theta_e, angle_el | rad |
| `omega_slip_rads` | slip, omega_slip | rad/s |

---

## Model Graph — Edge Types

| Edge type | Count | Meaning |
|---|---|---|
| `has_port` | 129 | Subsystem owns this port node |
| `compatible_with` | 1410 | Two ports share canonical name, domain, and solver — safe to wire |
| `fidelity_chain` | 2 | Two subsystems are the same component at different fidelity levels |
| `requires_input_from` | varies | Thermal input has no currently-connected EM source |

---

## Indexed Corpus (28 models)

| ID | Analysis type | Fidelity |
|---|---|---|
| `PMSM_FEM` | torque_accuracy | detailed |
| `PMSM_avg` | efficiency | simplified (fidelity_chain partner of PMSM_FEM) |
| `MotorThermal11Node` | thermal | detailed |
| `PMSMThermal11Node` | thermal | detailed |
| `FOCController` | drive_cycle | detailed |
| `FEM_IM` | torque_accuracy | detailed |
| `FEM_IM_FOC` | drive_cycle | detailed |
| `FEM_IM_FOC_FW` | drive_cycle | detailed (field-weakening variant) |
| `FEM_IM_FOC_MA` | drive_cycle | detailed (multi-agent built) |
| `FEM_IM_OpenLoop_reference` | torque_accuracy | detailed |
| `FEM_PMSM_lib` | torque_accuracy | detailed |
| `IMFluxMotorCAD` | torque_accuracy | detailed |
| `IPMSMTorque` | torque_accuracy | detailed |
| `IPMSMTorque_rebuilt` | torque_accuracy | detailed |
| `VF_Demo_IM` | drive_cycle | simplified |
| + 13 test/validation models | — | — |

---

## How to Get the Best Results

### Tag your subsystems

Add to each subsystem's `Description` field in MATLAB:

```
fidelity_tier: detailed
analysis_type: torque_accuracy
solver_contract: continuous
```

### Use named ports

| Signal | Good name | Bad name |
|---|---|---|
| Shaft speed | `omega_shaft_rads` or `SpeedPS` | `Out1` |
| Electromagnetic torque | `torque_shaft_Nm` or `TPS` | `2` |
| Copper loss | `loss_copper_W` or `SL2PS_Copper_Loss` | `signal_out` |
| Iron loss | `loss_iron_W` or `SL2PS_Rotor_Iron_Loss` | `Out3` |

### Use SL2PS_/PS2SL_ bridge naming

SimVault detects `SL2PS_*` and `PS2SL_*` block names automatically:
- `SL2PS_Copper_Loss` → port `Copper_Loss` → canonical `loss_copper_W`
- `PS2SL_AirGap` → port `AirGap` → canonical `temperature_K`

---

## Agent Assembly Protocol

```
1. DISCOVER   → simvault_search(query, fidelity_tier?, analysis_type?)
2. CONTEXT    → simvault_get_assembly_context([id1, id2, ...])
3. VALIDATE   → simvault_validate_wire(src_id, src_port, dst_id, dst_port)
4. BUILD      → model_edit (using ONLY canonical port names from step 2)
5. RE-INDEX   → simvault index <dir> --skip-matlab
```

**Never guess port names.** Use `simvault_get_assembly_context` — the canonical names are the ground truth from the actual `.slx` files.

Also query KB history before building:
```
simvault_kb_query("<model_id> pitfalls decisions validated results")
```

---

## Stop Hook Integration

The `integrations/claude_code/` directory contains a shell script that runs `simvault kb-update` automatically at the end of every Claude Code session. Install it by adding to your `.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [
      { "matcher": "", "hooks": [{ "type": "command", "command": "/path/to/SimVault/integrations/claude_code/stop_hook.sh" }] }
    ]
  }
}
```

---

## Dependencies

```
turbovec>=0.1.0          4-bit quantized vector index (replaces ChromaDB)
sentence-transformers>=2.7.0  BAAI/bge-small-en-v1.5 embeddings
networkx>=3.0            model knowledge graph
rank-bm25>=0.2.2         BM25Okapi keyword index for KB chunks
mcp>=1.0                 MCP SDK (stdio transport)
anthropic>=0.40.0        LLM fact extraction (claude-haiku-4-5-20251001)
click>=8.0               CLI
numpy>=1.24.0
```

Python ≥ 3.11 required. MATLAB R2024a+ required for extraction (Python pipeline runs without MATLAB if JSONs exist).

---

## Contributors

| Name | Role |
|---|---|
| [Sooraj Krishnan](https://github.com/nightfury1802) | Creator — architecture, Simscape modeling, corpus design |
| [Claude Sonnet 4.6](https://anthropic.com) | Implementation partner |

---

## Roadmap

- [ ] Phase 2: `simvault_smoke_test` wired to MATLAB MCP for real simulation checks
- [ ] Phase 3: WLTP drive-cycle integration test (T9 → T10)
- [ ] Phase 4: Auto-tag script that reads port labels from `.slx` XML directly (no MATLAB required)
- [ ] Phase 5: Multi-repo federation (index across teams)
