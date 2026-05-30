"""Port canonicalizer: maps raw port names to canonical names and writes Markdown specs."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from glob import glob
from math import pi
from pathlib import Path
from typing import Literal


# ---------------------------------------------------------------------------
# Canonical map — (pattern, canonical_name, canonical_unit, rpm_scale_map)
# Patterns are applied case-insensitively. Earlier entries win.
# ---------------------------------------------------------------------------
CANONICAL_MAP: list[tuple[str, str, str, dict]] = [
    # Shaft speed (various RPM/rad/s naming conventions)
    (r"omega|speed|w_out|w_shaft|n_shaft|speedps|speedsens|wr\b|omega_r",
     "omega_shaft_rads", "rad/s",
     {"rpm": 2 * pi / 60, "RPM": 2 * pi / 60}),

    # Torque
    (r"torque|trq|^T$|t_out|tau|tps\b|torqsens|torque_shaft",
     "torque_shaft_Nm", "N*m", {}),

    # Temperatures (expanded to cover T_*_K, winding_K, vector_K, TPS_* block names)
    (r"T_winding|temp|temperature|t_pm|T_stator|T_rotor|tem_|AirGap|EndCap|"
     r"EndSpace|EndWinding|Frame|Magnets|RotorIron|Shaft|SlotWinding|"
     r"StatorTooth|StatorYoke|winding_K|vector_K|TPS_Core|TPS_Winding|TPS_Magnet",
     "temperature_K", "K",
     {"_degC": "+273.15", "_C": "+273.15"}),

    # d-axis stator current (isd in induction machine notation)
    (r"^isd|^i_sd|isd_A",  "id_current_A",  "A", {}),

    # q-axis stator current (isq in induction machine notation)
    (r"^isq|^i_sq|isq_A",  "iq_current_A",  "A", {}),

    # d-axis current (PMSM notation)
    (r"^id$|^Id$|i_d|id_curr|id_ref",   "id_current_A",  "A", {}),

    # q-axis current (PMSM notation)
    (r"^iq$|^Iq$|i_q|iq_curr|iq_ref",   "iq_current_A",  "A", {}),

    # DC bus voltage
    (r"Vdc|v_dc|VDC|DC_voltage|vdc", "vdc_V", "V", {}),

    # Copper losses (various naming from SL2PS block names in MotorThermal models)
    (r"Q_copper|P_copper|Pcu|copper_loss|Copper_Loss|CopperLoss|"
     r"End_Winding_Copper|Side_Winding_Copper",
     "loss_copper_W", "W", {}),

    # Iron losses (SL2PS_Rotor_Iron_Loss, SL2PS_Stator_Teeth_Loss, etc.)
    (r"Q_iron|P_iron|Pfe|iron_loss|Iron_Loss|IronLoss|"
     r"Stator_Teeth_Loss|Stator_Yoke_Loss|Rotor_Iron_Loss|Magnet_Eddy",
     "loss_iron_W", "W", {}),

    # d-axis flux linkage
    (r"flux_d|lambda_d|psi_d",   "flux_d_Wb",     "Wb", {}),

    # q-axis flux linkage
    (r"flux_q|lambda_q|psi_q",   "flux_q_Wb",     "Wb", {}),

    # 3-phase voltage (abc frame)
    (r"vabc|v_abc|Vabc",  "vabc_V",   "V", {}),

    # 3-phase current (abc frame) — covers iabc_A, ia_A/ib_A/ic_A
    (r"iabc|i_abc|Iabc|^ia_|^ib_|^ic_|^ia$|^ib$|^ic$",  "iabc_A",  "A", {}),

    # Field angle / electrical angle
    (r"field_angle|theta_e|angle_rad|angle_el",  "field_angle_rad", "rad", {}),

    # Slip frequency (induction machine)
    (r"slip|omega_slip",  "omega_slip_rads", "rad/s", {}),
    (r"iabc|i_abc|Iabc",  "iabc_A",   "A", {}),

    # Slip (induction machine)
    (r"slip|omega_slip",  "omega_slip_rads", "rad/s", {}),
]


@dataclass
class PortSpec:
    original_name: str
    direction: str
    port_type: str
    domain: str
    units: str
    canonical_name: str = ""
    canonical_units: str = ""
    unit_mismatch: bool = False
    scale_factor: float | None = None
    canonicalized: bool = False


def canonicalize_port(port: dict) -> dict:
    """Add canonical_name, canonical_units, unit_mismatch, scale_factor, canonicalized."""
    name = port.get("original_name", "")
    raw_units = port.get("units", "unknown")

    for pattern, cname, cunits, scale_map in CANONICAL_MAP:
        if re.search(pattern, name, re.IGNORECASE):
            scale = None
            mismatch = False
            if raw_units != "unknown" and raw_units != cunits:
                mismatch = True
                scale = scale_map.get(raw_units)

            return {
                **port,
                "canonical_name":  cname,
                "canonical_units": cunits,
                "unit_mismatch":   mismatch,
                "scale_factor":    scale,
                "canonicalized":   True,
            }

    return {
        **port,
        "canonical_name":  "",
        "canonical_units": raw_units,
        "unit_mismatch":   False,
        "scale_factor":    None,
        "canonicalized":   False,
    }


def canonicalize(json_path: str, kb_dir: str = "kb/models") -> list[Path]:
    """Canonicalize all subsystems in a model JSON. Returns list of written .md paths."""
    with open(json_path) as f:
        meta = json.load(f)

    model_name = meta["model_name"]
    out_paths: list[Path] = []

    Path(kb_dir).mkdir(parents=True, exist_ok=True)

    for ss in meta.get("subsystems", []):
        # Canonicalize ports in-place
        ss["ports"] = [canonicalize_port(p) for p in ss.get("ports", [])]

        # Write Markdown spec
        md_path = _write_markdown_spec(ss, model_name, kb_dir)
        out_paths.append(md_path)

    # Write updated JSON back
    with open(json_path, "w") as f:
        json.dump(meta, f, indent=2)

    return out_paths


def canonicalize_all(extracted_dir: str, kb_dir: str = "kb/models") -> None:
    """Canonicalize all JSON files in extracted_dir."""
    files = glob(f"{extracted_dir}/*.json")
    if not files:
        print(f"No JSON files found in {extracted_dir}")
        return
    for path in sorted(files):
        paths = canonicalize(path, kb_dir)
        for p in paths:
            print(f"  Wrote: {p}")


# ---------------------------------------------------------------------------
# Markdown spec writer
# ---------------------------------------------------------------------------

def _write_markdown_spec(ss: dict, model_name: str, kb_dir: str) -> Path:
    tags = ss.get("tags", {})
    subsys_name = ss.get("name", ss.get("id", "unknown"))
    safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", subsys_name)
    filename = f"{model_name}_{safe_name}.md"
    out_path = Path(kb_dir) / filename

    ports = ss.get("ports", [])
    inputs  = [p for p in ports if p.get("direction") == "input"]
    outputs = [p for p in ports if p.get("direction") == "output"]
    bidir   = [p for p in ports if p.get("direction") == "bidirectional"]

    # Compatibility alerts
    alerts = _build_alerts(ports, ss)

    lines = [
        "---",
        f"fidelity_tier: {tags.get('fidelity_tier', 'unknown')}",
        f"analysis_type: {tags.get('analysis_type', 'unknown')}",
        f"solver_contract: {tags.get('solver_contract', 'unknown')}",
        f"source_file: {ss.get('source_file', '')}",
        f"source_hash: {ss.get('source_hash', '')}",
        f"block_count: {ss.get('block_count', -1)}",
        f"state_count: {ss.get('state_count', -1)}",
        "---",
        "",
        f"# {model_name} / {subsys_name}",
        "",
        ss.get("causal_summary", f"Subsystem: {subsys_name}"),
        "",
    ]

    if alerts:
        lines += ["## Compatibility Alerts", ""]
        for a in alerts:
            lines.append(f"- ⚠️  {a}")
        lines.append("")

    if inputs:
        lines += ["## Inputs", "", _port_table(inputs), ""]
    if outputs:
        lines += ["## Outputs", "", _port_table(outputs), ""]
    if bidir:
        lines += ["## Physical (bidirectional)", "", _port_table(bidir), ""]

    out_path.write_text("\n".join(lines))
    return out_path


def _port_table(ports: list[dict]) -> str:
    header = "| Original name | Canonical name | Domain | Units | Canonicalized |"
    sep    = "|---|---|---|---|---|"
    rows   = []
    for p in ports:
        status = "✓" if p.get("canonicalized") else "—"
        rows.append(
            f"| {p.get('original_name','')} "
            f"| {p.get('canonical_name','')} "
            f"| {p.get('domain','')} "
            f"| {p.get('canonical_units', p.get('units',''))} "
            f"| {status} |"
        )
    return "\n".join([header, sep] + rows)


def _build_alerts(ports: list[dict], ss: dict) -> list[str]:
    alerts: list[str] = []
    canonical_names = {p.get("canonical_name") for p in ports}

    # Alert: thermal model has iron loss input but no copper loss (or vice versa)
    has_iron   = "loss_iron_W"   in canonical_names
    has_copper = "loss_copper_W" in canonical_names

    if has_iron and not has_copper:
        alerts.append("loss_copper_W input missing — thermal model may need copper loss source")
    if has_copper and not has_iron:
        alerts.append("loss_iron_W input missing — thermal model may need iron loss source")
    if has_iron:
        alerts.append("loss_iron_W present — ensure EM source provides this port (check compatible_with edges)")

    # Alert: unit mismatches
    for p in ports:
        if p.get("unit_mismatch") and p.get("scale_factor") is not None:
            alerts.append(
                f"Unit mismatch on '{p['original_name']}': "
                f"{p.get('units','?')} → {p.get('canonical_units','?')} "
                f"(scale: {p['scale_factor']})"
            )

    return alerts
