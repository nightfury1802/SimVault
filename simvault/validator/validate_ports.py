"""Port connection validator: PASS / WARN / BLOCK for proposed wires."""
from __future__ import annotations

from dataclasses import dataclass, field
from math import pi
from typing import Literal


UNIT_CONVERSION_TABLE: dict[tuple[str, str], float | str] = {
    ("rpm",  "rad/s"): 2 * pi / 60,
    ("rad/s", "rpm"):  60 / (2 * pi),
    ("degC", "K"):     "+273.15",
    ("K",    "degC"):  "-273.15",
    ("W",    "kW"):    0.001,
    ("kW",   "W"):     1000.0,
}

SOLVER_BRIDGE_TABLE: dict[tuple[str, str], str] = {
    ("continuous", "discrete"):    "Rate Transition",
    ("discrete",   "continuous"):  "Rate Transition",
    ("continuous", "steady_state"): "Operating Point",
    ("steady_state", "continuous"): "Operating Point",
}


@dataclass
class PortSpec:
    original_name:    str = ""
    canonical_name:   str = ""
    canonical_units:  str = "unknown"
    direction:        str = "output"
    port_type:        str = "signal"
    domain:           str = "signal"
    solver_contract:  str = "continuous"
    subsystem_id:     str = ""

    @classmethod
    def from_node(cls, node_data: dict, subsystem_data: dict | None = None) -> "PortSpec":
        spec = cls(
            original_name   = node_data.get("original_name",   ""),
            canonical_name  = node_data.get("canonical_name",  ""),
            canonical_units = node_data.get("canonical_units",
                              node_data.get("units", "unknown")),
            direction       = node_data.get("direction",  "output"),
            port_type       = node_data.get("port_type",  "signal"),
            domain          = node_data.get("domain",     "signal"),
        )
        if subsystem_data:
            spec.solver_contract = subsystem_data.get("solver_contract", "continuous")
            spec.subsystem_id    = subsystem_data.get("id", "")
        return spec


@dataclass
class ValidationResult:
    result:                Literal["PASS", "WARN", "BLOCK"]
    reason:                str = ""
    required_bridge_block: str = ""
    gain_factor:           float | None = None

    def model_dump_json(self) -> str:
        import json
        return json.dumps({
            "result":                self.result,
            "reason":                self.reason,
            "required_bridge_block": self.required_bridge_block,
            "gain_factor":           self.gain_factor,
        })


def validate_wire(src: PortSpec, dst: PortSpec) -> ValidationResult:
    """
    Validate a proposed connection from src (output port) to dst (input port).

    Rule 1 — Domain mismatch: BLOCK
    Rule 2 — Direction conflict: BLOCK
    Rule 3 — Unit mismatch: WARN with gain or BLOCK if unknown conversion
    Rule 4 — Solver contract mismatch: WARN with bridge block
    """
    # Rule 1: domain must match
    if src.domain != dst.domain:
        return ValidationResult(
            "BLOCK",
            reason=(
                f"Domain mismatch: {src.domain} → {dst.domain}. "
                f"Cannot connect {src.port_type} port to {dst.port_type} port "
                f"across domain boundary."
            ),
        )

    # Rule 2: direction must be compatible (src=output, dst=input, or bidirectional)
    def _compat(d1: str, d2: str) -> bool:
        if d1 == "bidirectional" or d2 == "bidirectional":
            return True
        return {d1, d2} == {"input", "output"}

    if not _compat(src.direction, dst.direction):
        return ValidationResult(
            "BLOCK",
            reason=f"Direction conflict: {src.direction} → {dst.direction}",
        )

    # Rule 3: unit mismatch
    u1, u2 = src.canonical_units, dst.canonical_units
    if u1 != u2 and u1 != "unknown" and u2 != "unknown":
        factor = UNIT_CONVERSION_TABLE.get((u1, u2))
        if factor is None:
            return ValidationResult(
                "BLOCK",
                reason=f"Incompatible units: {u1} ≠ {u2} — no known conversion",
            )
        gain_val = float(factor) if isinstance(factor, (int, float)) else None
        return ValidationResult(
            "WARN",
            reason=f"Unit scale required: {u1} → {u2}",
            required_bridge_block=f"Gain (factor: {factor})",
            gain_factor=gain_val,
        )

    # Rule 4: solver contract mismatch
    c1, c2 = src.solver_contract, dst.solver_contract
    if c1 != c2:
        bridge = SOLVER_BRIDGE_TABLE.get((c1, c2), "")
        return ValidationResult(
            "WARN",
            reason=f"Solver mismatch: {c1} ↔ {c2}",
            required_bridge_block=bridge,
        )

    return ValidationResult("PASS")


def load_port(
    json_dir: str,
    subsystem_id: str,
    canonical_name: str,
) -> PortSpec:
    """Load a PortSpec from extracted JSON by subsystem_id and canonical port name."""
    import json as _json
    from glob import glob
    from pathlib import Path

    for f in glob(f"{json_dir}/*.json"):
        meta = _json.loads(Path(f).read_text())
        for ss in meta.get("subsystems", []):
            if ss["id"] != subsystem_id:
                continue
            for p in ss.get("ports", []):
                if p.get("canonical_name") == canonical_name:
                    return PortSpec.from_node(p, {
                        "solver_contract": ss.get("tags", {}).get("solver_contract", "continuous"),
                        "id": ss["id"],
                    })
    raise ValueError(f"Port '{canonical_name}' not found in subsystem '{subsystem_id}'")
