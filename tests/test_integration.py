"""
SimVault integration tests.
Run from SimVault/ directory: python -m pytest tests/ -v
Requires: extracted/ JSONs + .svdb/ + simvault.graph.json (built by `simvault index`)
"""
import json
import os
import sys
from pathlib import Path

import pytest

# Ensure SimVault root is on path
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
os.chdir(_ROOT)

from simvault.canonicalizer.canonicalize import canonicalize_port
from simvault.graph.build_graph import load_graph
from simvault.query.query import query
from simvault.validator.validate_ports import PortSpec, validate_wire


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def G():
    """Load the pre-built graph once for all tests."""
    graph_path = _ROOT / "simvault.graph.json"
    assert graph_path.exists(), f"Graph not found: {graph_path}. Run `simvault index` first."
    return load_graph(str(graph_path))


@pytest.fixture(scope="session")
def thermal_subsystem():
    p = _ROOT / "extracted" / "MotorThermal11Node.json"
    assert p.exists(), "Run `simvault index` first."
    meta = json.loads(p.read_text())
    return meta["subsystems"][0]


@pytest.fixture(scope="session")
def pmsm_fem_subsystem():
    p = _ROOT / "extracted" / "PMSM_FEM.json"
    assert p.exists(), "Run `simvault index` first."
    meta = json.loads(p.read_text())
    return meta["subsystems"][0]


# ---------------------------------------------------------------------------
# T-canon: Canonicalization
# ---------------------------------------------------------------------------

class TestCanonicalization:
    def test_omega_rpm_to_rads(self):
        """omega_shaft in RPM → canonical omega_shaft_rads with scale 0.1047"""
        port = {"original_name": "omega_rpm", "units": "rpm", "domain": "signal",
                "direction": "output", "port_type": "signal", "canonical_name": ""}
        result = canonicalize_port(port)
        assert result["canonical_name"] == "omega_shaft_rads"
        assert abs(result["scale_factor"] - 0.1047) < 0.001, f"Got {result['scale_factor']}"

    def test_rotor_iron_loss_to_canonical(self):
        """Rotor_Iron_Loss → loss_iron_W"""
        port = {"original_name": "Rotor_Iron_Loss", "units": "W", "domain": "signal",
                "direction": "input", "port_type": "signal", "canonical_name": ""}
        result = canonicalize_port(port)
        assert result["canonical_name"] == "loss_iron_W"
        assert result["canonicalized"] is True

    def test_copper_loss_to_canonical(self):
        """End_Winding_Copper_Loss → loss_copper_W"""
        port = {"original_name": "End_Winding_Copper_Loss", "units": "W", "domain": "signal",
                "direction": "input", "port_type": "signal", "canonical_name": ""}
        result = canonicalize_port(port)
        assert result["canonical_name"] == "loss_copper_W"

    def test_temperature_to_canonical(self):
        """AirGap → temperature_K"""
        port = {"original_name": "AirGap", "units": "K", "domain": "signal",
                "direction": "output", "port_type": "signal", "canonical_name": ""}
        result = canonicalize_port(port)
        assert result["canonical_name"] == "temperature_K"


# ---------------------------------------------------------------------------
# T-val: Validator
# ---------------------------------------------------------------------------

class TestValidator:
    def _port(self, domain="signal", direction="output", units="W",
               port_type="signal", solver="continuous"):
        return PortSpec(domain=domain, direction=direction, canonical_units=units,
                        port_type=port_type, solver_contract=solver)

    def test_validate_wire_domain_mismatch_blocks(self):
        """Simscape thermal port → Simulink signal must return BLOCK"""
        src = self._port(domain="thermal", direction="output", units="K", port_type="physical")
        dst = self._port(domain="signal",  direction="input",  units="unknown")
        assert validate_wire(src, dst).result == "BLOCK"

    def test_validate_wire_unit_mismatch_warns(self):
        """rad/s → rpm must return WARN with gain_factor ≈ 9.549"""
        src = self._port(units="rad/s")
        dst = self._port(direction="input", units="rpm")
        result = validate_wire(src, dst)
        assert result.result == "WARN"
        assert result.required_bridge_block.startswith("Gain")
        assert result.gain_factor is not None
        assert abs(result.gain_factor - 9.549) < 0.01

    def test_validate_wire_pass(self):
        """Same domain, direction, units → PASS"""
        src = self._port(direction="output", units="W")
        dst = self._port(direction="input",  units="W")
        assert validate_wire(src, dst).result == "PASS"

    def test_validate_direction_conflict_blocks(self):
        """output → output must BLOCK"""
        src = self._port(direction="output")
        dst = self._port(direction="output")
        assert validate_wire(src, dst).result == "BLOCK"

    def test_validate_solver_mismatch_warns(self):
        """continuous ↔ discrete must WARN with Rate Transition"""
        src = self._port(solver="continuous")
        dst = self._port(direction="input", solver="discrete")
        result = validate_wire(src, dst)
        assert result.result == "WARN"
        assert "Rate Transition" in result.required_bridge_block


# ---------------------------------------------------------------------------
# T-graph: Graph structure
# ---------------------------------------------------------------------------

class TestGraph:
    def test_graph_has_fidelity_chain(self, G):
        """FEM motor and averaged motor must be linked by fidelity_chain edge"""
        edges = [(u, v, d) for u, v, d in G.edges(data=True)
                 if d.get("type") == "fidelity_chain"]
        assert len(edges) >= 1, "No fidelity_chain edges found"

    def test_fidelity_chain_links_pmsm_variants(self, G):
        """PMSM_FEM and PMSM_avg must have a fidelity_chain edge"""
        fchain_pairs = {
            frozenset([u, v])
            for u, v, d in G.edges(data=True)
            if d.get("type") == "fidelity_chain"
        }
        assert frozenset(["PMSM_FEM", "PMSM_avg"]) in fchain_pairs

    def test_graph_has_compatible_with_edges(self, G):
        """Graph must have at least 1 compatible_with edge"""
        edges = [(u, v) for u, v, d in G.edges(data=True)
                 if d.get("type") == "compatible_with"]
        assert len(edges) >= 1

    def test_thermal_model_in_graph(self, G):
        """MotorThermal11Node must be a node in the graph"""
        assert "MotorThermal11Node" in G.nodes

    def test_subsystem_tags_preserved(self, G):
        """Nodes should carry fidelity_tier tags"""
        pmsm = G.nodes.get("PMSM_FEM", {})
        assert pmsm.get("fidelity_tier") == "detailed"
        assert pmsm.get("analysis_type") == "torque_accuracy"


# ---------------------------------------------------------------------------
# T-query: Query engine
# ---------------------------------------------------------------------------

class TestQuery:
    @pytest.fixture(scope="class", autouse=True)
    def check_db(self):
        db = _ROOT / ".svdb"
        if not db.exists():
            pytest.skip("Vector DB not built — run `simvault index` first.")

    def test_query_returns_pmsm_candidate(self):
        """Search for FEM PMSM returns a PMSM model"""
        result = query("high-fidelity PMSM", top_k=5)
        candidate_ids = [c.subsystem_id for c in result.candidates]
        assert any("PMSM" in id for id in candidate_ids), f"Got: {candidate_ids}"

    def test_fidelity_filter_excludes_simplified(self):
        """Query with fidelity_tier=detailed must not return PMSM_avg (simplified)"""
        result = query("PMSM motor", fidelity_tier="detailed", top_k=10)
        for c in result.candidates:
            assert c.fidelity_tier == "detailed", (
                f"Expected only detailed, got {c.subsystem_id} ({c.fidelity_tier})"
            )

    def test_thermal_in_subgraph_for_pmsm_query(self):
        """Query for PMSM should include thermal model in expanded subgraph"""
        result = query("high-fidelity PMSM thermal", top_k=5)
        all_ids = list(result.subgraph.nodes)
        assert any("Thermal" in id or "thermal" in id.lower() for id in all_ids), (
            f"Thermal model not in subgraph. Nodes: {all_ids}"
        )

    def test_query_has_valid_wires(self):
        """Broad PMSM query should return at least some valid wires in the subgraph"""
        result = query("PMSM motor drive system", top_k=6)
        assert len(result.validated_wires) > 0, "Expected some valid wires"

    def test_induction_motor_query(self):
        """Query for induction motor FOC should return FEM_IM or FEM_IM_FOC_MA"""
        result = query("induction motor FOC drive cycle", top_k=5)
        candidate_ids = [c.subsystem_id for c in result.candidates]
        assert any("FEM_IM" in id for id in candidate_ids), (
            f"IM model not found. Got: {candidate_ids}"
        )


# ---------------------------------------------------------------------------
# T-thermal: Thermal model port structure
# ---------------------------------------------------------------------------

class TestThermalModel:
    def test_thermal_has_iron_loss_input(self, thermal_subsystem):
        """Thermal model must have at least one loss_iron_W input"""
        canonical_inputs = [
            p.get("canonical_name")
            for p in thermal_subsystem.get("ports", [])
            if p.get("direction") == "input"
        ]
        assert "loss_iron_W" in canonical_inputs, f"Inputs: {canonical_inputs}"

    def test_thermal_has_copper_loss_input(self, thermal_subsystem):
        """Thermal model must have at least one loss_copper_W input"""
        canonical_inputs = [
            p.get("canonical_name")
            for p in thermal_subsystem.get("ports", [])
            if p.get("direction") == "input"
        ]
        assert "loss_copper_W" in canonical_inputs, f"Inputs: {canonical_inputs}"

    def test_thermal_has_temperature_output(self, thermal_subsystem):
        """Thermal model must have temperature_K outputs"""
        canonical_outputs = [
            p.get("canonical_name")
            for p in thermal_subsystem.get("ports", [])
            if p.get("direction") == "output"
        ]
        assert "temperature_K" in canonical_outputs, f"Outputs: {canonical_outputs}"

    def test_thermal_tags_correct(self, thermal_subsystem):
        """Thermal model must be tagged detailed/thermal/continuous"""
        tags = thermal_subsystem.get("tags", {})
        assert tags.get("fidelity_tier") == "detailed"
        assert tags.get("analysis_type") == "thermal"
        assert tags.get("solver_contract") == "continuous"
