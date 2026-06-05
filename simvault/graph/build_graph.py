"""Build a NetworkX graph from canonicalized model JSON files."""
from __future__ import annotations

import json
import re
from glob import glob
from itertools import combinations
from pathlib import Path
from typing import Any

import networkx as nx


# ---------------------------------------------------------------------------
# Fidelity suffix list for stem-matching
# ---------------------------------------------------------------------------
FIDELITY_SUFFIXES = [
    "_fem", "_avg", "_averaged", "_lookup", "_lut",
    "_surrogate", "_nn", "_simplified", "_detailed",
    "_highfidelity", "_hifi", "_reduced",
]

FIDELITY_ORDER = ["detailed", "simplified", "lookup", "untagged"]


def _stem(name: str) -> str:
    """Strip fidelity suffix from model/subsystem name for chain matching."""
    low = name.lower()
    for suffix in FIDELITY_SUFFIXES:
        if low.endswith(suffix):
            return name[: len(name) - len(suffix)]
    # Also strip trailing numbers (PMSM_FEM vs PMSM_avg → stem "PMSM")
    stripped = re.sub(r"(_fem|_avg|_FEM|_avg)$", "", name)
    return stripped


def _parent_subsystem(port_id: str, G: nx.DiGraph) -> str | None:
    """Find the subsystem node that has a has_port edge to this port_id."""
    for pred in G.predecessors(port_id):
        if G.nodes[pred].get("type") == "subsystem":
            return pred
    return None


# ---------------------------------------------------------------------------
# Compatibility checks
# ---------------------------------------------------------------------------

def _directions_compatible(d1: str, d2: str) -> bool:
    """input↔output or bidirectional↔anything are compatible."""
    pair = {d1, d2}
    if "bidirectional" in pair:
        return True
    return pair == {"input", "output"}


def _units_compatible(u1: str, u2: str) -> bool:
    """Same units or one of the known convertible pairs."""
    if u1 == u2:
        return True
    convertible = {
        frozenset(["rad/s", "rpm"]),
        frozenset(["K", "degC"]),
        frozenset(["W", "kW"]),
    }
    return frozenset([u1, u2]) in convertible


def _solver_contracts_compatible(d1: dict, d2: dict) -> bool:
    """Two subsystems are solver-compatible if same contract or one is continuous."""
    c1 = d1.get("solver_contract", "continuous")
    c2 = d2.get("solver_contract", "continuous")
    return c1 == c2 or "continuous" in (c1, c2)


def _get_scale_factor(u1: str, u2: str) -> float | None:
    from math import pi
    table = {
        ("rpm", "rad/s"):  2 * pi / 60,
        ("rad/s", "rpm"):  60 / (2 * pi),
        ("W", "kW"):       0.001,
        ("kW", "W"):       1000.0,
    }
    return table.get((u1, u2))


# ---------------------------------------------------------------------------
# Edge builders
# ---------------------------------------------------------------------------

def _add_compatible_with_edges(G: nx.DiGraph) -> None:
    port_nodes = [n for n, d in G.nodes(data=True) if d.get("type") == "port"]
    for p1, p2 in combinations(port_nodes, 2):
        d1, d2 = G.nodes[p1], G.nodes[p2]

        # Must belong to different subsystems
        parent1 = _parent_subsystem(p1, G)
        parent2 = _parent_subsystem(p2, G)
        if parent1 is None or parent2 is None or parent1 == parent2:
            continue

        # Domain must match (or both be signal)
        if d1.get("domain") != d2.get("domain"):
            continue

        # Direction must be compatible
        if not _directions_compatible(d1.get("direction", ""), d2.get("direction", "")):
            continue

        # Canonical names must match (same physical quantity)
        cn1 = d1.get("canonical_name", "")
        cn2 = d2.get("canonical_name", "")
        if not cn1 or not cn2 or cn1 != cn2:
            continue

        # Solver contracts
        sp1 = G.nodes.get(parent1, {})
        sp2 = G.nodes.get(parent2, {})
        if not _solver_contracts_compatible(sp1, sp2):
            continue

        u1 = d1.get("canonical_units", "unknown")
        u2 = d2.get("canonical_units", "unknown")

        G.add_edge(
            p1, p2,
            type="compatible_with",
            scale_factor=_get_scale_factor(u1, u2),
        )
        G.add_edge(
            p2, p1,
            type="compatible_with",
            scale_factor=_get_scale_factor(u2, u1),
        )


def _add_fidelity_chain_edges(G: nx.DiGraph) -> None:
    subsystems = [(n, d) for n, d in G.nodes(data=True) if d.get("type") == "subsystem"]
    for (n1, d1), (n2, d2) in combinations(subsystems, 2):
        short1 = n1.split("/")[-1]
        short2 = n2.split("/")[-1]
        if _stem(short1) == _stem(short2) and d1.get("fidelity_tier") != d2.get("fidelity_tier"):
            G.add_edge(n1, n2, type="fidelity_chain")
            G.add_edge(n2, n1, type="fidelity_chain")


def _add_requires_input_from_edges(G: nx.DiGraph) -> None:
    """Add requires_input_from edges: thermal inputs that need EM sources."""
    subsystems = [(n, d) for n, d in G.nodes(data=True) if d.get("type") == "subsystem"]

    for ss_node, ss_data in subsystems:
        if ss_data.get("analysis_type") != "thermal":
            continue
        # Find unmatched loss inputs
        for port_id in G.successors(ss_node):
            pd = G.nodes[port_id]
            if pd.get("type") != "port":
                continue
            if pd.get("direction") != "input":
                continue
            cn = pd.get("canonical_name", "")
            if cn not in ("loss_copper_W", "loss_iron_W"):
                continue
            # Check if it has a compatible_with partner
            has_partner = any(
                G.edges[port_id, nb].get("type") == "compatible_with"
                for nb in G.successors(port_id)
            )
            if not has_partner:
                # Find subsystems that OUTPUT this canonical name
                for other_ss, _ in subsystems:
                    if other_ss == ss_node:
                        continue
                    for other_port in G.successors(other_ss):
                        opd = G.nodes[other_port]
                        if (opd.get("type") == "port"
                                and opd.get("direction") == "output"
                                and opd.get("canonical_name") == cn):
                            G.add_edge(
                                ss_node, other_ss,
                                type="requires_input_from",
                                canonical_name=cn,
                            )
                            break


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_graph(canonicalized_dir: str) -> nx.DiGraph:
    G = nx.DiGraph()

    for json_file in sorted(glob(f"{canonicalized_dir}/*.json")):
        meta = json.loads(Path(json_file).read_text())
        for subsystem in meta.get("subsystems", []):
            ss_id = subsystem["id"]
            tags = subsystem.get("tags", {})

            G.add_node(
                ss_id,
                type="subsystem",
                fidelity_tier=tags.get("fidelity_tier", "unknown"),
                analysis_type=tags.get("analysis_type", "unknown"),
                solver_contract=tags.get("solver_contract", "continuous"),
                block_count=subsystem.get("block_count", -1),
                state_count=subsystem.get("state_count", -1),
                source_hash=subsystem.get("source_hash", ""),
                source_file=subsystem.get("source_file", ""),
                causal_summary=subsystem.get("causal_summary", ""),
            )

            for port in subsystem.get("ports", []):
                port_id = f"{ss_id}/ports/{port.get('canonical_name') or port.get('original_name')}"
                # Make unique if multiple ports share the same canonical name
                if G.has_node(port_id):
                    port_id = f"{ss_id}/ports/{port.get('original_name')}"

                G.add_node(port_id, type="port", **port)
                G.add_edge(ss_id, port_id, type="has_port")

    _add_compatible_with_edges(G)
    _add_fidelity_chain_edges(G)
    _add_requires_input_from_edges(G)

    return G


def save_graph(G: nx.DiGraph, path: str = "simvault.graph.json") -> None:
    data = nx.node_link_data(G)
    Path(path).write_text(json.dumps(data, indent=2))


def load_graph(path: str = "simvault.graph.json") -> nx.DiGraph:
    data = json.loads(Path(path).read_text())
    edge_key = "links" if "links" in data else "edges"
    return nx.node_link_graph(data, directed=True, multigraph=False, edges=edge_key)


def graph_summary(G: nx.DiGraph) -> str:
    n_subsystems = sum(1 for _, d in G.nodes(data=True) if d.get("type") == "subsystem")
    n_ports      = sum(1 for _, d in G.nodes(data=True) if d.get("type") == "port")
    edge_types: dict[str, int] = {}
    for _, _, d in G.edges(data=True):
        t = d.get("type", "unknown")
        edge_types[t] = edge_types.get(t, 0) + 1

    lines = [
        f"Nodes: {G.number_of_nodes()} ({n_subsystems} subsystems, {n_ports} ports)",
        f"Edges: {G.number_of_edges()}",
    ]
    for t, count in sorted(edge_types.items()):
        lines.append(f"  {t}: {count}")
    return "\n".join(lines)
