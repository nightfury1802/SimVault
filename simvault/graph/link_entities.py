"""
Cross-edge linker: draws 'discusses_model' edges between SimVault model nodes
and KB graph nodes (session logs, pitfalls) that mention them.
Writes store/cross_edges.json — does NOT modify graphify's graph.json.
"""
import json
from pathlib import Path
from typing import Optional
from ..knowledge.config import GRAPH_PATH, STORE_DIR

_HERE = Path(__file__).parent.parent.parent
SIMVAULT_GRAPH_PATH = _HERE / "simvault.graph.json"
CROSS_EDGES_PATH = STORE_DIR / "cross_edges.json"


def find_kb_nodes_mentioning(model_id: str, kb_graph: dict) -> list[dict]:
    """Find KB graph nodes that mention a model ID in their label or source_file."""
    term = model_id.lower()
    return [
        n for n in kb_graph.get("nodes", [])
        if term in n.get("label", "").lower()
        or term in n.get("source_file", "").lower()
    ]


def load_simvault_model_ids(path: Optional[Path] = None) -> list[str]:
    """Load all subsystem IDs from the SimVault graph."""
    p = path or SIMVAULT_GRAPH_PATH
    if not p.exists():
        return []
    data = json.loads(p.read_text())
    return [n["id"] for n in data.get("nodes", []) if n.get("type") == "subsystem"]


def build_cross_edges(model_ids: list[str], kb_graph: dict) -> list[dict]:
    """Build cross-edges from KB nodes to SimVault model nodes."""
    seen, edges = set(), []
    for model_id in model_ids:
        for kb_node in find_kb_nodes_mentioning(model_id, kb_graph):
            pair = (kb_node["id"], model_id)
            if pair in seen:
                continue
            seen.add(pair)
            edges.append({
                "source": kb_node["id"],
                "target": model_id,
                "relation": "discusses_model",
                "confidence": 0.9,
                "source_file": kb_node.get("source_file", ""),
            })
    return edges


def run() -> int:
    """
    Main entry point: link KB graph nodes to SimVault models.
    Writes store/cross_edges.json.
    Returns the count of cross-edges created.
    """
    if not GRAPH_PATH.exists():
        print(f"[link_entities] KB graph not found: {GRAPH_PATH}")
        return 0
    kb_graph = json.loads(GRAPH_PATH.read_text())
    model_ids = load_simvault_model_ids()
    if not model_ids:
        print("[link_entities] No SimVault model IDs found.")
        return 0
    edges = build_cross_edges(model_ids, kb_graph)
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    CROSS_EDGES_PATH.write_text(json.dumps({"edges": edges}, indent=2))
    print(f"[link_entities] {len(edges)} cross-edges → {CROSS_EDGES_PATH}")
    return len(edges)
