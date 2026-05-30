# SimVault

**A knowledge graph and semantic search engine for Simscape/Simulink component libraries — built so AI agents can assemble physically-valid models without hallucinating wires.**

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
    ├──► build_graph.py     ← NetworkX: compatible_with / fidelity_chain / requires_input_from
    │
    └──► index.py           ← ChromaDB + BGE-small-en-v1.5 semantic embeddings
                                        │
                    validate_ports.py   │   ← PASS / WARN / BLOCK wire validator
                                        │
                              query.py  │   ← semantic search + graph expansion
                                        │
                          mcp_server.py ─── ← 4 MCP tools for Claude agents
                              cli.py        ← command-line interface
```

---

## Quick Start

```bash
git clone https://github.com/nightfury1802/SimVault.git
cd SimVault
pip install -e .

# 1. Tag your models (run once in MATLAB)
matlab -batch "run('examples/tag_models_for_simvault.m')"

# 2. Index
simvault index examples/pmsm_drive/

# 3. Query
simvault query "PMSM thermal model" --fidelity detailed

# 4. Validate a proposed wire
simvault validate \
  --src "PMSM_FEM/omega_shaft_rads" \
  --dst "FOCController/omega_shaft_rads"
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

---

## Canonical Port Names

The canonicalizer maps raw port/block names to a fixed vocabulary so the graph can detect compatibility:

| Canonical name | Matches | Units |
|---|---|---|
| `omega_shaft_rads` | omega, speed, w_shaft, SpeedPS, wr, omega_r, speed_ref, speed_cmd | rad/s |
| `torque_shaft_Nm` | torque, TPS, trq, tau, torque_ref | N·m |
| `temperature_K` | temp, AirGap, Frame, Magnets, Shaft, winding_K, vector_K, TPS_Core, TPS_Winding, … | K |
| `loss_copper_W` | Copper_Loss, End_Winding_Copper_Loss, Side_Winding_Copper, Pcu | W |
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

## How to Get the Best Results from Your Models

The richer your model's port metadata, the more useful SimVault becomes.

### Add SimVault tags to your key subsystem's Description field

```
fidelity_tier: detailed
analysis_type: torque_accuracy
solver_contract: continuous
```

### Use named Inport/Outport blocks (not numbered)

Instead of unnamed ports, give each one a descriptive name that matches the canonical vocabulary:

| Signal | Good name | Bad name |
|---|---|---|
| Shaft speed | `omega_shaft_rads` or `SpeedPS` | `Out1` |
| Electromagnetic torque | `torque_shaft_Nm` or `TPS` | `2` |
| Copper loss (to thermal) | `loss_copper_W` | `signal_out` |
| Iron loss (to thermal) | `loss_iron_W` | `Out3` |
| d-axis current | `id` | `input_1` |

### Add unit tags to port descriptions

```
units: rad/s
domain: signal
```

This lets the validator catch unit mismatches (e.g. `rpm` → `rad/s` needs a Gain block with factor 0.1047).

### Use SL2PS_/PS2SL_ naming for physical-signal bridges

The parser automatically detects these block naming patterns and converts them to named ports:

- `SL2PS_Copper_Loss` → port name `Copper_Loss` → canonical `loss_copper_W`
- `PS2SL_AirGap` → port name `AirGap` → canonical `temperature_K`

---

## Graph Edge Types

| Edge type | Meaning |
|---|---|
| `compatible_with` | Two ports share the same canonical name, domain, and solver contract |
| `fidelity_chain` | Two subsystems represent the same component at different fidelity levels |
| `requires_input_from` | A thermal model input has no currently-connected EM source |
| `has_port` | Subsystem owns this port node |

---

## Test Results

```
23 passed in 14.71s

TestCanonicalization  4/4  — omega_rpm→rad/s, Rotor_Iron_Loss, Copper_Loss, AirGap
TestValidator         5/5  — domain BLOCK, unit WARN (gain=9.549), PASS, direction, solver
TestGraph             5/5  — fidelity_chain, PMSM_FEM↔PMSM_avg, compatible_with edges
TestQuery             5/5  — fidelity filter, thermal in subgraph, IM query, wires
TestThermalModel      4/4  — loss_iron_W, loss_copper_W, temperature_K, tags
```

---

## Sample Corpus

Drop your `.slx` files into `examples/pmsm_drive/`, tag them, and index. A well-rounded corpus for an IPMSM drive system includes:

| Type | What it represents | Key ports to expose |
|---|---|---|
| FEM motor (detailed) | High-fidelity electromagnetic model | `omega_shaft_rads`, `torque_shaft_Nm`, `loss_copper_W`, `loss_iron_W` |
| Averaged motor (simplified) | Same machine, reduced order | same as FEM — enables fidelity swap |
| 11-node thermal model | RC thermal network | `loss_copper_W` + `loss_iron_W` inputs, `temperature_K` outputs |
| FOC controller | Closed-loop drive | `omega_shaft_rads`, `id_ref_A`, `iq_ref_A` |
| Induction machine | Different machine type | `iabc_A`, `omega_shaft_rads` |
| Agent-built model | Any model built in a prior session | whatever ports that session exposed |

The last row is the meta-test: every model an agent builds should be immediately re-indexed so future agents can reuse it.

---

## Dependencies

```
chromadb>=0.4          vector store
sentence-transformers>=2.2   BGE-small-en-v1.5 embeddings
networkx>=3.0          knowledge graph
mcp>=1.0               MCP SDK
click>=8.0             CLI
numpy>=1.24
```

Python ≥ 3.10 required. MATLAB R2024a+ required for extraction (Python pipeline runs without MATLAB if JSONs exist).

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
