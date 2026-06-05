"""
Unified query engine. Routes to turbovec (KB semantic), BM25 (keyword),
graphify BFS (relationship), and cross-edges (model+KB), then fuses with RRF
and applies decay-adjusted confidence scoring.
"""
import json
from pathlib import Path
from typing import Optional

from ..knowledge.query_kb import (
    SIMVAULT_MODEL_IDS,
    semantic_search,
    graph_traverse,
    classify_query as _kb_classify,
)
from ..knowledge.config import CHUNK_MAP_PATH, GRAPHIFY_CACHE_DIR, STORE_DIR
from ..memory.scorer import effective_confidence
from .bm25 import BM25Index
from .rrf import reciprocal_rank_fusion

_CROSS_EDGES_PATH = STORE_DIR / "cross_edges.json"


def classify_unified_query(query: str) -> str:
    """
    Route classification (priority order):
      1. relationship — if relationship keywords detected
      2. model+kb     — if a known model ID is mentioned
      3. kb           — default
    """
    # Relationship detection takes highest priority
    if _kb_classify(query) == "relationship":
        return "relationship"
    # Model ID mention is next
    q = query.lower()
    if any(mid.lower() in q for mid in SIMVAULT_MODEL_IDS):
        return "model+kb"
    return "kb"


def _load_bm25() -> Optional[BM25Index]:
    if not CHUNK_MAP_PATH.exists():
        return None
    chunk_map = json.loads(CHUNK_MAP_PATH.read_text())
    # indexer.py stores rel paths as chunk_file.relative_to(cache_dir.parent),
    # so they look like "cache/ast/foo.json". from_chunk_map does cache_dir / rel_path,
    # therefore cache_dir must be GRAPHIFY_CACHE_DIR.parent (i.e. graphify-out/).
    return BM25Index.from_chunk_map(chunk_map, GRAPHIFY_CACHE_DIR.parent)


def _cross_edge_results(model_ids: list[str]) -> list[dict]:
    if not _CROSS_EDGES_PATH.exists():
        return []
    edges = json.loads(_CROSS_EDGES_PATH.read_text()).get("edges", [])
    return [
        {
            "id": e["source"],
            "score": e["confidence"],
            "source": e.get("source_file", ""),
            "text": f"[discusses {e['target']}]",
            "mode": "cross_edge",
        }
        for e in edges
        if e["target"] in model_ids
    ]


def _apply_decay(results: list[dict]) -> list[dict]:
    out = []
    for r in results:
        eff = effective_confidence(
            {
                "tier": r.get("tier", "episodic"),
                "confidence": r.get("confidence", 0.75),
                "created_at": r.get("created_at"),
                "valid_until": r.get("valid_until"),
                "superseded_by": r.get("superseded_by"),
            }
        )
        out.append({**r, "effective_score": round(r.get("score", 0.5) * eff, 6)})
    return sorted(out, key=lambda x: x["effective_score"], reverse=True)


class UnifiedQuery:
    def __init__(self):
        self._bm25 = _load_bm25()

    def search(self, query: str, k: int = 10) -> list[dict]:
        qtype = classify_unified_query(query)
        lists: list[list[dict]] = []

        if qtype == "relationship":
            lists.append(graph_traverse(query, k=k))
            lists.append(semantic_search(query, k=3))
        else:
            lists.append(semantic_search(query, k=k))
            if self._bm25:
                lists.append(self._bm25.search(query, k=k))
            if qtype == "model+kb":
                mentioned = [m for m in SIMVAULT_MODEL_IDS if m.lower() in query.lower()]
                lists.append(_cross_edge_results(mentioned))

        # Ensure every result has an 'id' field for RRF
        for result_list in lists:
            for r in result_list:
                r.setdefault("id", r.get("source", "unknown"))

        merged = reciprocal_rank_fusion(lists)
        return _apply_decay(merged)[:k]
