"""
Hybrid KB retrieval: semantic search (turbovec) + graph traversal (graphify BFS).
Routes based on keyword classification.
"""
import json
import subprocess
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer
from turbovec import IdMapIndex

from .config import INDEX_PATH, CHUNK_MAP_PATH, GRAPH_PATH, EMBED_MODEL_NAME

SIMVAULT_MODEL_IDS = [
    "PMSM_FEM", "PMSM_avg", "MotorThermal11Node",
    "FOCController", "FEM_IM", "FEM_IM_FOC_MA",
]

_RELATIONSHIP_KEYWORDS = [
    "connect", "relate", "path", "between", "dependency", "depends on",
    "link", "how does", "why does", "trace", "chain", "what uses",
    "what calls", "multi-hop", "relationship", "upstream", "downstream",
    "flow", "pipeline", "sequence",
]


def classify_query(query: str) -> str:
    """Return 'relationship', 'model', or 'content'."""
    q = query.lower()
    if any(kw in q for kw in _RELATIONSHIP_KEYWORDS):
        return "relationship"
    if any(mid.lower() in q for mid in SIMVAULT_MODEL_IDS):
        return "model"
    return "content"


def semantic_search(query: str, k: int = 5) -> list[dict]:
    """Search turbovec index for knowledge chunks (excludes model entries)."""
    if not INDEX_PATH.exists() or not CHUNK_MAP_PATH.exists():
        return []

    chunk_map = json.loads(CHUNK_MAP_PATH.read_text())
    id_to_path = {
        v["id"]: (key, v.get("source_file", ""))
        for key, v in chunk_map.items()
        if v.get("source_type") == "knowledge"
    }
    if not id_to_path:
        return []

    model = SentenceTransformer(EMBED_MODEL_NAME)
    q_vec = model.encode([query], normalize_embeddings=True)[0].astype(np.float32)

    index = IdMapIndex.load(str(INDEX_PATH))
    scores_mat, ids_mat = index.search(q_vec.reshape(1, -1), k=k * 3)
    raw_ids, raw_scores = ids_mat[0], scores_mat[0]

    results = []
    seen = set()
    cache_root = Path(__file__).parent.parent.parent / "graphify-out"
    for chunk_id, score in zip(raw_ids, raw_scores):
        entry = id_to_path.get(int(chunk_id))
        if entry is None:
            continue
        rel_path, source_file = entry
        if rel_path in seen:
            continue
        seen.add(rel_path)

        # Try to load the text from the cache file
        text = ""
        cache_file = cache_root / rel_path
        if not cache_file.exists():
            alt_path = rel_path.replace("cache/ast/", "cache/semantic/")
            cache_file = cache_root / alt_path

        if cache_file.exists():
            try:
                cache_data = json.loads(cache_file.read_text())
                text_parts = [
                    n["label"] for n in cache_data.get("nodes", []) if n.get("label")
                ]
                text = " | ".join(text_parts)[:300]
            except (json.JSONDecodeError, KeyError):
                pass

        # Prefer the original source_file over the hash-based chunk path
        display_source = source_file or rel_path
        results.append({
            "id": rel_path,
            "score": float(score),
            "source": display_source,
            "text": text,
            "mode": "semantic",
        })
        if len(results) >= k:
            break
    return results


def graph_traverse(query_text: str, k: int = 5) -> list[dict]:
    """BFS traversal via graphify CLI."""
    try:
        result = subprocess.run(
            ["graphify", "query", query_text, "--graph", str(GRAPH_PATH)],
            capture_output=True, text=True, timeout=30,
        )
        output = result.stdout.strip()
        if not output:
            return []
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    results = []
    for i, block in enumerate(output.split("\n\n")[:k]):
        lines = [l.strip() for l in block.strip().splitlines() if l.strip()]
        if not lines:
            continue
        source = next((l for l in lines if "/" in l or "." in l), "graph-traversal")
        results.append({
            "id": source,
            "score": 1.0 - (i * 0.05),
            "source": source,
            "text": " | ".join(lines[:4])[:300],
            "mode": "graph",
        })
    return results


def run(query: str, k: int = 5, mode: str = "auto") -> list[dict]:
    if mode == "auto":
        mode = classify_query(query)
    if mode == "relationship":
        results = graph_traverse(query, k=k) or semantic_search(query, k=k)
    else:
        results = semantic_search(query, k=k)
    return sorted(results, key=lambda r: r["score"], reverse=True)
