# Premortem Transcript — Simulation Repository Vector Embedding Pipeline
Generated: 2026-05-29

## What was premortemed

**What it is:** A vector embedding pipeline for a large simulation repository containing .slx (Simulink) and .ame (AMESim) files, organized by analysis type (efficiency, drive cycle, torque accuracy, inefficiency analysis). Each type contains motors, inverters, gearboxes at multiple fidelity levels with thermal, EM, and driveline submodels.

**Who it's for:** Powertrain simulation engineer at BorgWarner. Team of engineers maintaining the repository independently.

**Success criteria:** AI agent receives a use case (e.g., "build a 150kW efficiency analysis model with high-fidelity PMSM and thermal") and assembles a working, physically consistent simulation by retrieving and wiring subsystems from the repository.

**Proposed pipeline:**
1. Parse .slx/.ame via simulink MCP `model_overview` → structured JSON
2. LLM generates 2-3 sentence functional summary per subsystem
3. Embed (text summary + JSON schema) with text embedding model
4. Store in TurboVec with metadata = JSON + summary + port schema
5. Agent queries TurboVec → retrieves JSON → LLM assembles via `model_edit`

---

## Raw Premortem — 8 Failure Reasons

1. Embedding space collapses — FEM motor and averaged motor get identical vectors; short LLM summaries can't distinguish fidelity levels
2. Port domain mismatch — Simscape HeatPort silently wired to Simulink double signal; no error thrown; thermal states frozen
3. Fidelity mismatch at assembly — iron loss input port on thermal model unconnected because averaged EM model has no such output; zero losses for months
4. Parameter drift / version hell — stale index returns 2022 gearbox with Gen3 motor; no re-indexing trigger; wrong results to customer
5. Maintenance burden kills adoption — one person owns re-indexing; no CI hook; shelfware in 3 months
6. Case-type metadata lost in semantic space — steady-state gearbox assembled with transient motor; solver contract mismatch; wrong results for both use cases
7. LLM hallucinates connection code — Id/Iq swapped (copper loss 40% low); gear ratio reference inverted (inertia wrong by ratio²=85x); both plausible at steady-state
8. Naming convention chaos — omega_shaft vs w_out vs shaft_speed_rpm (RPM vs rad/s); LLM guesses port names; 60%+ cross-engineer connection failure rate

---

## Agent Deep-Dives

### Agent 1 — Embedding Space Collapse

**Story:** FEM and averaged motors both summarized as "PMSM computing torque from dq currents." Cosine distance 0.05. Agent retrieved averaged motor for efficiency query. Ran three weeks before iron losses found to be zero and thermal states absent.

**Underlying Assumption:** Short natural-language summaries preserve physically meaningful distinctions between simulation fidelity levels.

**Early Warning Signs:**
- Two components with 6 vs 60 blocks return cosine similarity above 0.90
- Assembled model's state count after structural_simplify is lower than expected

---

### Agent 2 — Port Domain Mismatch

**Story:** Both subsystems had port named `T_motor`. One: Simscape `foundation.thermal.thermal`. Other: Simulink `double` in Celsius. LLM matched by name. Simulink accepted the wire. Thermal states never updated. Six months of efficiency validation at 25°C. Caught when drive cycle pushed motor to 140°C.

**Underlying Assumption:** Port name equality implies physical domain compatibility and solver contract compatibility.

**Early Warning Signs:**
- TurboVec metadata shows `type: "double"` for every port with no domain field
- First model_edit assembly produces no error but downstream sim() fails with opaque algebraic loop diagnostic

---

### Agent 3 — Fidelity Mismatch

**Story:** High-fidelity 11-node thermal model assembled with averaged EM model. Thermal model's iron loss input port had no driver — averaged EM model has no iron loss output. Defaulted to zero. Winding temperature error 22°C at high-speed light-load. Caught only at Motor-CAD validation six months later.

**Underlying Assumption:** Semantic similarity of component descriptions is a sufficient proxy for physical interface compatibility.

**Early Warning Signs:**
- Assembled models simulate without errors but contain unconnected thermal loss input ports
- Iron loss channel in logged output identically zero across all operating points above 1000 RPM

---

### Agent 4 — Parameter Drift / Version Hell

**Story:** Index last rebuilt in February. Gen3 motor team pushed three flux map updates, revised d-axis inductance by 11%. Gearbox from 2022 efficiency campaign (pre Gen3 ratio change) retrieved alongside it. Simulation passed all checks. 4% efficiency error vs dyno. Two days to trace version forensically via binary .slx diffing.

**Underlying Assumption:** A model's identity is stable once named, so a match on semantic description implies a match on current parameter values.

**Early Warning Signs:**
- Index modification timestamp more than 2 weeks behind latest repo commit
- Two engineers querying same component get different simulation results from different index versions

---

### Agent 5 — Maintenance Burden / Shelfware

**Story:** Designer pulled onto vehicle program. Re-indexing in a README only. Engineers got deprecated single-node inverter thermal model. Word spread: "the agent gives you old stuff." Usage dropped to near zero. Index sat, increasingly wrong, until server was repurposed.

**Underlying Assumption:** Initial accuracy is durable. A retrieval system is only as trustworthy as its worst recent staleness event.

**Early Warning Signs:**
- Re-indexing has no CI hook or cron job — lives only in one person's README
- Query returns subsystem description referencing port name renamed more than two weeks ago

---

### Agent 6 — Case-Type Metadata Lost

**Story:** Query for "high-fidelity IPMSM with planetary gearbox for vehicle efficiency study" returned IPMSM from drive_cycle folder + gearbox from efficiency folder. Both tagged "high-efficiency." Neither encoded its solver contract. Efficiency values varied by 3–5% with drive cycle snapshot location. Hardware team sized a cooling system from these numbers.

**Underlying Assumption:** Semantic similarity of component descriptions implies compatibility of operational context and solver contract.

**Early Warning Signs:**
- Assembled model has inconsistent solver settings between subsystems
- Efficiency values vary by more than 3–5% depending on snapshot location in drive cycle

---

### Agent 7 — LLM Assembly Hallucination

**Story:** Id and Iq ports swapped because both described as "electrical ports carrying dq-frame current." Copper losses 40% low for six weeks of thermal validation. Gear ratio reference shaft wired as output instead of input — reflected inertia wrong by ratio² = 85x. NVH team spent three weeks on apparent damping coefficient error upstream.

**Underlying Assumption:** A model that simulates without error and produces plausible steady-state results is physically correct.

**Early Warning Signs:**
- Steady-state matches but transient time constants inconsistent with known component inertias by more than 20%
- Copper loss at known operating point disagrees with datasheet lookup by more than a few percent

---

### Agent 8 — Naming Convention Chaos

**Story:** omega_shaft, w_out, shaft_speed_rpm — three engineers, three names. RPM vs rad/s is a units error (factor 2π/60). LLM matched by name fragment. 60%+ cross-engineer connection failure rate. Gearbox output torques 10x too low. No assertion caught it. Deprecated after third integration cycle.

**Underlying Assumption:** Port names are stable, unique identifiers for physical quantities — but they are free-form strings with no enforced contract between name, units, and physics.

**Early Warning Signs:**
- First integration test across two different engineers' subsystems fails or produces wrong result
- TurboVec metadata for semantically equivalent ports returns more than one distinct name string

---

## Synthesis

### Most Likely Failure
Naming conventions collapse assembly at scale. A multi-engineer repository over years will have incompatible port names and units. The LLM guesses from summaries. 60%+ cross-engineer connections fail or silently mismatch.

### Most Dangerous Failure
Silent physics errors that ship to customers. Port domain mismatch and LLM assembly errors (Id/Iq swap, gear ratio inversion) produce models that simulate without errors, look plausible, and are wrong by 10–40% in ways that surface only at customer delivery or dyno validation.

### The Hidden Assumption
Semantic similarity of text descriptions is a proxy for physical assembly compatibility. Every failure traces back to this. Physical compatibility is a function of port domain, solver contract, units, fidelity tier, analysis context, and version — none reliably captured by short LLM-generated summaries. The pipeline is being treated as an assembly planner when it is only a search engine.

### Revised Plan
1. Split retrieval from assembly — use TurboVec for semantic search only; use rule-based port-matching for wiring
2. Add hard structured metadata — fidelity_tier, analysis_type, solver_contract, port domain + units — as mandatory fields, not derived from text
3. Port canonicalization before indexing — normalize all port names and units across the repository; enforce via pre-commit hook
4. Automated re-indexing on every model commit — SHA hash per source file; stale entries flagged before retrieval
5. Assembly validation harness as mandatory gate — check unconnected thermal ports, state count, rated operating point spot-check after every LLM assembly

### Pre-Launch Checklist
- [ ] Port canonicalization table covers all shaft, thermal, and electrical ports across full repository
- [ ] Every subsystem has explicit fidelity_tier, analysis_type, solver_contract metadata fields
- [ ] Port schema includes Simscape physical domain type, not just port name
- [ ] Re-indexing is automated (CI hook or file-watcher), not manual
- [ ] Assembly validation harness passes on 3 known-good manually assembled models
