# SimVault — Agent Instructions

SimVault is the model knowledge graph for this project. Before assembling any Simscape/Simulink model,
you MUST query SimVault first. Never guess port names. Never hardcode canonical names from memory.
The index is the ground truth — it reflects the actual ports in the actual .slx files.

---

## The Assembly Workflow

Follow this exact sequence every time you are asked to build or modify a Simulink model:

```
1. DISCOVER   → simvault_search
2. CONTEXT    → simvault_get_assembly_context
3. VALIDATE   → simvault_validate_wire  (for any uncertain connection)
4. BUILD      → model_edit  (using ONLY canonical port names from step 2)
5. RE-INDEX   → simvault index .  (so the new model is reusable by future agents)
```

---

## Step 1 — DISCOVER: `simvault_search`

```
simvault_search(
  query: str,                      # natural language — be descriptive
  fidelity_tier?: str,             # "detailed" | "simplified" | "lookup"
  analysis_type?: str,             # "torque_accuracy" | "efficiency" | "thermal" | "drive_cycle"
  solver_contract?: str,           # "continuous" | "discrete" | "steady_state"
  top_k?: int = 5
)
```

Use hard filters (`fidelity_tier`, `analysis_type`) to narrow before semantic ranking.
A query without filters returns all fidelity levels — use filters when you need a specific one.

**Example calls:**
```
# Find a high-fidelity thermal model
simvault_search("11-node thermal model for IPMSM", fidelity_tier="detailed", analysis_type="thermal")

# Find anything that can provide copper/iron losses
simvault_search("PMSM motor copper iron loss outputs")

# Find induction motor FOC controller
simvault_search("induction machine field oriented control drive cycle")
```

**What you get back:** ranked list of subsystem IDs + similarity scores + fidelity/analysis tags.
The subgraph section also shows which models are already connected in the knowledge graph.

---

## Step 2 — CONTEXT: `simvault_get_assembly_context`

```
simvault_get_assembly_context(
  subsystem_ids: list[str]         # model IDs from step 1
)
```

Call this with ALL the models you plan to connect. It returns:
- **Canonical port names** for each model (use these, not original names)
- **Solver info** (ode15s, continuous, etc.) — needed for model_edit solver config
- **Pre-validated wire pairs** — connections already confirmed as PASS between the selected models
- **Blocked pairs** — connections you must NOT make (domain mismatch, incompatible types)

**Example:**
```
simvault_get_assembly_context(["PMSM_FEM", "MotorThermal11Node"])
```

Returns something like:
```json
{
  "subsystems": [
    { "id": "PMSM_FEM", "tags": {...}, "ports": [
        {"canonical_name": "temperature_winding_K", "direction": "output", ...},
        {"canonical_name": "torque_shaft_Nm",       "direction": "output", ...}
    ]},
    { "id": "MotorThermal11Node", "ports": [
        {"canonical_name": "loss_copper_W",     "direction": "input", ...},
        {"canonical_name": "temperature_K",     "direction": "output", ...}
    ]}
  ],
  "validated_wires": [
    {"src": "PMSM_FEM/temperature_winding_K", "dst": "MotorThermal11Node/loss_copper_W",
     "result": "PASS", ...}
  ],
  "blocked_pairs": []
}
```

---

## Step 3 — VALIDATE: `simvault_validate_wire`

```
simvault_validate_wire(
  src_subsystem_id: str,
  src_port_canonical: str,         # canonical name, NOT original block name
  dst_subsystem_id: str,
  dst_port_canonical: str
)
```

Returns `PASS`, `WARN` (with required bridge block + gain factor), or `BLOCK` (with reason).

Call this whenever:
- The connection wasn't in the `validated_wires` list from step 2
- You're unsure about unit compatibility (e.g., rpm vs rad/s)
- The two models have different solver contracts

**WARN means:** connect the ports BUT insert the specified bridge block.
- `WARN` with `"Gain (factor: 0.1047)"` → add a Gain block between the two
- `WARN` with `"Rate Transition"` → add a Rate Transition block

**BLOCK means:** do NOT make this connection. Find an alternative or add a domain converter.

---

## Step 4 — BUILD: `model_edit`

Use the canonical port names and solver config from `simvault_get_assembly_context`.

Key rules:
- Port names in `model_edit` must match the canonical names exactly (case-sensitive)
- Always set solver to match the `solver_contract` from context (usually `ode15s`, `continuous`)
- If any wire had a WARN: add the bridge block BEFORE connecting the two ports
- Never connect ports from the BLOCKED list

---

## Step 5 — RE-INDEX: Always index new models

After building, run:
```bash
simvault index <directory-containing-new-slx> --skip-matlab
```

Or via MATLAB MCP: `extract_metadata(model_dir, 'extracted', 'simvault.lock.json')`
Then Python: `python -m simvault.cli index <dir>`

This ensures:
- Future agents can find and reuse the model you just built
- The `fidelity_chain` graph is updated if you built a variant of an existing model
- The T9 meta-test stays passing: agent-built models are reusable assets

---

## Port Name Reference

Never guess — query SimVault. But for quick reference, the canonical vocabulary is:

| Canonical name | Physical quantity | Units |
|---|---|---|
| `omega_shaft_rads` | Shaft speed | rad/s |
| `torque_shaft_Nm` | Shaft torque | N·m |
| `temperature_K` | Any node temperature | K |
| `temperature_winding_K` | Winding temperature specifically | K |
| `loss_copper_W` | Copper (I²R) losses | W |
| `loss_iron_W` | Iron / eddy / hysteresis losses | W |
| `id_current_A` | d-axis current (PMSM) or isd (IM) | A |
| `iq_current_A` | q-axis current (PMSM) or isq (IM) | A |
| `iabc_A` | 3-phase stator currents | A |
| `vabc_V` | 3-phase voltage commands | V |
| `vdc_V` | DC bus voltage | V |
| `field_angle_rad` | Field/electrical angle | rad |
| `omega_slip_rads` | Slip frequency (IM only) | rad/s |

---

## Indexed Models (current corpus)

| ID | Analysis type | Fidelity | Key outputs | Key inputs |
|---|---|---|---|---|
| `PMSM_FEM` | torque_accuracy | detailed | `temperature_winding_K`, `speed_cmd_rads`, `torque_shaft_Nm` | `id_ref_A`, `iq_ref_A` |
| `PMSM_avg` | efficiency | simplified | same as FEM | same as FEM |
| `MotorThermal11Node` | thermal | detailed | 11× `temperature_K`, `temperature_vector_K` | 6× loss ports (`loss_copper_W`, `loss_iron_W`) |
| `FOCController` | drive_cycle | detailed | `temperature_winding_K`, `speed_ref_rads` | `speed_ref_rads`, `torque_ref_Nm` |
| `FEM_IM` | torque_accuracy | detailed | `ia_A`, `ib_A`, `ic_A` | — |
| `FEM_IM_FOC_MA` | drive_cycle | detailed | `iabc_A`, `isd_A`, `isq_A`, `omega_shaft_rads` | `torque_ref_Nm`, `vabc_V` |

---

## Common Patterns

**Pattern: EM motor + thermal model**
```
1. simvault_search("FEM PMSM motor", fidelity_tier="detailed", analysis_type="torque_accuracy")
2. simvault_search("thermal model", analysis_type="thermal")
3. simvault_get_assembly_context(["PMSM_FEM", "MotorThermal11Node"])
4. Wire: PMSM_FEM/temperature_winding_K → MotorThermal11Node/loss_copper_W  (check if PASS first)
```

**Pattern: FOC drive system**
```
1. simvault_search("induction motor FOC", analysis_type="drive_cycle")
2. simvault_get_assembly_context(["FEM_IM_FOC_MA"])
3. Wire inputs: vabc_V from voltage controller, torque_ref_Nm from speed loop
4. Wire outputs: iabc_A and omega_shaft_rads to outer loop
```

**Pattern: Fidelity swap**
```
# Replace detailed motor with simplified for efficiency sweep:
1. simvault_search("PMSM motor", fidelity_tier="simplified")
   → returns PMSM_avg (fidelity_chain partner of PMSM_FEM)
2. simvault_get_assembly_context(["PMSM_avg", ...])
   → same canonical port names as PMSM_FEM — swap is drop-in
```

---

## Pitfalls

- **Do not wire a physical Simscape port to a Simulink signal port.** `simvault_validate_wire` will return BLOCK with "Domain mismatch". You need a PS-Simulink Converter block in between.
- **Do not assume PMSM and IM have the same port names.** They don't — always query SimVault for the actual model you're using.
- **After a WARN:** the connection is valid but needs a Gain or Rate Transition block. Add it before connecting, not after.
- **After building:** always re-index. An un-indexed model is invisible to all future agents.
