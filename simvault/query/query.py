"""Query engine: semantic search + graph expansion + port validation."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx

from simvault.graph.build_graph import load_graph
from simvault.validator.validate_ports import PortSpec, ValidationResult, validate_wire
from simvault.vectors.index import query_index


@dataclass
class CandidateResult:
    subsystem_id:  str
    fidelity_tier: str
    analysis_type: str
    solver_contract: str
    source_file:   str
    similarity:    float
    causal_summary: str = ""


@dataclass
class WireResult:
    src_port: str
    dst_port: str
    validation: ValidationResult


@dataclass
class QueryResult:
    candidates:       list[CandidateResult]
    subgraph:         nx.DiGraph
    validated_wires:  list[WireResult]
    blocked_pairs:    list[WireResult]
    similarity_scores: dict[str, float]


def query(
    text: str,
    fidelity_tier: str | None = None,
    analysis_type: str | None = None,
    solver_contract: str | None = None,
    top_k: int = 5,
    graph_depth: int = 2,
    store_dir: str = "store",
    graph_path: str = "simvault.graph.json",
) -> QueryResult:
    """
    Search SimVault for subsystems matching `text`.

    Steps:
    1. Hard filter by fidelity/analysis/solver (post-filter on turbovec results).
    2. Semantic search on indexed set.
    3. Graph expansion: add compatible_with, fidelity_chain, requires_input_from neighbors.
    4. Validate candidate wires in the subgraph.
    5. Return QueryResult.
    """
    # Step 1+2: semantic search with optional hard filters
    raw = query_index(
        text,
        fidelity_tier=fidelity_tier,
        analysis_type=analysis_type,
        solver_contract=solver_contract,
        top_k=top_k,
        store_dir=store_dir,
    )

    seed_ids: list[str] = raw["ids"][0] if raw["ids"] else []
    distances: list[float] = raw["distances"][0] if raw["distances"] else []
    meta_list: list[dict] = raw["metadatas"][0] if raw["metadatas"] else []

    candidates = [
        CandidateResult(
            subsystem_id=sid,
            fidelity_tier=m.get("fidelity_tier", ""),
            analysis_type=m.get("analysis_type", ""),
            solver_contract=m.get("solver_contract", ""),
            source_file=m.get("source_file", ""),
            similarity=1.0 - dist,
        )
        for sid, dist, m in zip(seed_ids, distances, meta_list)
    ]

    similarity_scores = {sid: 1.0 - dist for sid, dist in zip(seed_ids, distances)}

    # Step 3: graph expansion
    G = _safe_load_graph(graph_path)
    subgraph_nodes: set[str] = set(seed_ids)

    EXPAND_TYPES = {"compatible_with", "fidelity_chain", "requires_input_from", "analysis_context_match"}

    for node_id in list(seed_ids):
        if node_id not in G:
            continue
        # First include port nodes of this subsystem (via has_port edges)
        for neighbor in G.successors(node_id):
            edata = G.edges[node_id, neighbor]
            if edata.get("type") == "has_port":
                subgraph_nodes.add(neighbor)
                # From each port, expand compatible_with neighbors and their subsystems
                for n2 in G.successors(neighbor):
                    e2 = G.edges[neighbor, n2]
                    if e2.get("type") == "compatible_with":
                        subgraph_nodes.add(n2)
                        # Find the parent subsystem of compatible port
                        for pred in G.predecessors(n2):
                            if G.nodes[pred].get("type") == "subsystem":
                                subgraph_nodes.add(pred)
                                if graph_depth > 1:
                                    # Include ports of that subsystem too
                                    for n3 in G.successors(pred):
                                        if G.edges[pred, n3].get("type") == "has_port":
                                            subgraph_nodes.add(n3)
            elif edata.get("type") in EXPAND_TYPES:
                subgraph_nodes.add(neighbor)

    sub = G.subgraph(subgraph_nodes)

    # Step 4: validate candidate wires
    validated_wires: list[WireResult] = []
    blocked_pairs: list[WireResult] = []
    seen_pairs: set[frozenset] = set()

    for n1, n2, edata in sub.edges(data=True):
        if edata.get("type") != "compatible_with":
            continue
        key = frozenset([n1, n2])
        if key in seen_pairs:
            continue
        seen_pairs.add(key)

        d1, d2 = G.nodes.get(n1, {}), G.nodes.get(n2, {})
        if d1.get("type") != "port" or d2.get("type") != "port":
            continue

        p1 = _port_spec_from_node(n1, d1, G)
        p2 = _port_spec_from_node(n2, d2, G)
        vr = validate_wire(p1, p2)

        wr = WireResult(src_port=n1, dst_port=n2, validation=vr)
        if vr.result == "BLOCK":
            blocked_pairs.append(wr)
        else:
            validated_wires.append(wr)

    # Exclude blocked subsystems from subgraph
    blocked_ss = set()
    for wr in blocked_pairs:
        for part in [wr.src_port, wr.dst_port]:
            for pred in G.predecessors(part):
                if G.nodes[pred].get("type") == "subsystem":
                    blocked_ss.add(pred)

    clean_nodes = subgraph_nodes - blocked_ss
    clean_subgraph = G.subgraph(clean_nodes)

    return QueryResult(
        candidates=candidates,
        subgraph=clean_subgraph,
        validated_wires=validated_wires,
        blocked_pairs=blocked_pairs,
        similarity_scores=similarity_scores,
    )


def get_assembly_context(
    subsystem_ids: list[str],
    json_dir: str = "extracted/",
    graph_path: str = "simvault.graph.json",
) -> dict:
    """
    Build full assembly context for a list of subsystem IDs.
    Returns canonical port lists, solver info, and validated wire pairs.
    """
    G = _safe_load_graph(graph_path)

    subsystems: list[dict] = []
    for sid in subsystem_ids:
        meta = _load_subsystem_meta(sid, json_dir)
        if meta:
            subsystems.append(meta)

    # Collect all wires between the requested subsystems
    wires = []
    blocked = []
    for i, s1 in enumerate(subsystems):
        for s2 in subsystems[i + 1:]:
            pairs = _find_wires_between(s1, s2)
            for src_port, dst_port in pairs:
                sp = PortSpec.from_node(src_port, {"solver_contract": s1.get("tags", {}).get("solver_contract", "continuous")})
                dp = PortSpec.from_node(dst_port, {"solver_contract": s2.get("tags", {}).get("solver_contract", "continuous")})
                vr = validate_wire(sp, dp)
                entry = {
                    "src": f"{s1['id']}/{src_port.get('original_name','')}",
                    "dst": f"{s2['id']}/{dst_port.get('original_name','')}",
                    "canonical": src_port.get("canonical_name", ""),
                    "result": vr.result,
                    "reason": vr.reason,
                    "bridge": vr.required_bridge_block,
                }
                if vr.result == "BLOCK":
                    blocked.append(entry)
                else:
                    wires.append(entry)

    return {
        "subsystems": [
            {
                "id": s["id"],
                "tags": s.get("tags", {}),
                "solver": s.get("solver", {}),
                "ports": s.get("ports", []),
                "causal_summary": s.get("causal_summary", ""),
            }
            for s in subsystems
        ],
        "validated_wires": wires,
        "blocked_pairs": blocked,
    }


def format_result(result: QueryResult) -> str:
    lines = [f"{'─'*60}", "SimVault Query Results", f"{'─'*60}"]
    for c in result.candidates:
        score = f"{c.similarity:.3f}"
        lines.append(f"  [{score}] {c.subsystem_id}")
        lines.append(f"         {c.fidelity_tier} / {c.analysis_type} / {c.solver_contract}")
    lines.append(f"\nSubgraph: {result.subgraph.number_of_nodes()} nodes")
    lines.append(f"Valid wires: {len(result.validated_wires)}")
    for wr in result.validated_wires[:5]:
        lines.append(f"  PASS  {wr.src_port} → {wr.dst_port}")
    if result.blocked_pairs:
        lines.append(f"Blocked: {len(result.blocked_pairs)}")
        for wr in result.blocked_pairs[:3]:
            lines.append(f"  BLOCK {wr.src_port} — {wr.validation.reason}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_load_graph(graph_path: str) -> nx.DiGraph:
    p = Path(graph_path)
    if p.exists():
        return load_graph(graph_path)
    return nx.DiGraph()


def _port_spec_from_node(node_id: str, node_data: dict, G: nx.DiGraph) -> PortSpec:
    ss_data: dict = {}
    for pred in G.predecessors(node_id):
        if G.nodes[pred].get("type") == "subsystem":
            ss_data = G.nodes[pred]
            break
    return PortSpec.from_node(node_data, ss_data)


def _load_subsystem_meta(subsystem_id: str, json_dir: str) -> dict | None:
    from glob import glob
    for f in glob(f"{json_dir}/*.json"):
        meta = json.loads(Path(f).read_text())
        for ss in meta.get("subsystems", []):
            if ss["id"] == subsystem_id:
                return ss
    return None


def _find_wires_between(s1: dict, s2: dict) -> list[tuple[dict, dict]]:
    """Find pairs of ports with matching canonical names across two subsystems."""
    pairs = []
    ports1 = {p.get("canonical_name"): p for p in s1.get("ports", []) if p.get("canonical_name")}
    ports2 = {p.get("canonical_name"): p for p in s2.get("ports", []) if p.get("canonical_name")}

    for cn in ports1:
        if cn in ports2:
            p1, p2 = ports1[cn], ports2[cn]
            if p1.get("direction") != p2.get("direction"):
                if p1.get("direction") == "output":
                    pairs.append((p1, p2))
                else:
                    pairs.append((p2, p1))
    return pairs
