"""
Vector store indexer: embed model/subsystem summaries into turbovec.
Replaces ChromaDB. One turbovec IdMapIndex (store/kb.tq) holds model embeddings.
Metadata (fidelity, analysis, solver, source_hash) stored in store/chunk_map.json.
query_index() returns the same dict shape as the old ChromaDB implementation so
query.py and all existing tests need zero changes.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer
from turbovec import IdMapIndex

_MODEL_NAME = "BAAI/bge-small-en-v1.5"
_EMBED_DIM = 384

_embed_model: SentenceTransformer | None = None


def _get_embed_model() -> SentenceTransformer:
    global _embed_model
    if _embed_model is None:
        _embed_model = SentenceTransformer(_MODEL_NAME)
    return _embed_model


def _model_chunk_id(model_id: str) -> int:
    """Stable uint63 ID for a model subsystem."""
    return int(hashlib.md5(f"model::{model_id}".encode()).hexdigest()[:16], 16) % (2**63)


def _store_paths(store_dir: str | Path) -> tuple[Path, Path]:
    store = Path(store_dir)
    return store / "kb.tq", store / "chunk_map.json"


def _has_port(subsystem: dict, canonical_name: str, direction: str) -> bool:
    return any(
        p.get("canonical_name") == canonical_name and p.get("direction") == direction
        for p in subsystem.get("ports", [])
    )


def _output_domains(subsystem: dict) -> list[str]:
    return list({
        p.get("domain", "signal")
        for p in subsystem.get("ports", [])
        if p.get("direction") == "output"
    })


def _input_domains(subsystem: dict) -> list[str]:
    return list({
        p.get("domain", "signal")
        for p in subsystem.get("ports", [])
        if p.get("direction") == "input"
    })


def _build_doc(subsystem: dict) -> str:
    """Build rich text embedding document from subsystem metadata."""
    tags = subsystem.get("tags", {})
    ports = subsystem.get("ports", [])
    canonical_names = [p.get("canonical_name") for p in ports if p.get("canonical_name")]
    original_names = [p.get("original_name") for p in ports if p.get("original_name")]

    parts = [
        subsystem.get("causal_summary", ""),
        f"Model: {subsystem.get('name', '')}",
        f"Fidelity: {tags.get('fidelity_tier', 'unknown')}",
        f"Analysis: {tags.get('analysis_type', 'unknown')}",
        f"Solver: {tags.get('solver_contract', 'continuous')}",
        f"Canonical ports: {', '.join(sorted(set(canonical_names)))}",
        f"Port names: {', '.join(original_names)}",
    ]
    return " | ".join(p for p in parts if p.strip())


def build_index(canonicalized_dir: str, store_dir: str = "store") -> None:
    """
    Index all model JSON files in canonicalized_dir into store/kb.tq.
    Incremental: skips subsystems whose source_hash is unchanged.
    Metadata stored in store/chunk_map.json under key 'model::<id>'.
    """
    store = Path(store_dir)
    store.mkdir(parents=True, exist_ok=True)
    index_path, chunk_map_path = _store_paths(store_dir)

    chunk_map: dict = json.loads(chunk_map_path.read_text()) if chunk_map_path.exists() else {}

    files = sorted(Path(canonicalized_dir).glob("*.json"))
    if not files:
        print(f"[vectors] No JSON files in {canonicalized_dir}")
        return

    new_ids, new_docs, new_map_entries = [], [], []

    for json_file in files:
        data = json.loads(json_file.read_text())
        for subsystem in data.get("subsystems", []):
            ss_id = subsystem["id"]
            map_key = f"model::{ss_id}"
            tags = subsystem.get("tags", {})

            if chunk_map.get(map_key, {}).get("source_hash") == subsystem.get("source_hash"):
                continue

            doc = _build_doc(subsystem)
            chunk_id = _model_chunk_id(ss_id)
            new_ids.append(chunk_id)
            new_docs.append(doc)
            new_map_entries.append((map_key, {
                "id": chunk_id,
                "source_type": "model",
                "tier": "procedural",
                "fidelity": tags.get("fidelity_tier", "unknown"),
                "analysis": tags.get("analysis_type", "unknown"),
                "solver": tags.get("solver_contract", "continuous"),
                "source_file": subsystem.get("source_file", ""),
                "source_hash": subsystem.get("source_hash", ""),
                "model_id": ss_id,
                "block_count": subsystem.get("block_count", -1),
                "state_count": subsystem.get("state_count", -1),
                "has_iron_loss_input": _has_port(subsystem, "loss_iron_W", "input"),
                "has_copper_loss_input": _has_port(subsystem, "loss_copper_W", "input"),
                "output_domains": ",".join(_output_domains(subsystem)),
                "input_domains": ",".join(_input_domains(subsystem)),
            }))

    if not new_ids:
        print("[vectors] All model entries up to date.")
        return

    embed = _get_embed_model()
    vecs = embed.encode(new_docs, normalize_embeddings=True)

    if index_path.exists():
        index = IdMapIndex.load(str(index_path))
        for chunk_id in new_ids:
            index.remove(chunk_id)  # remove stale entry if present; returns False (not exception) if absent
    else:
        index = IdMapIndex(_EMBED_DIM, bit_width=4)

    index.add_with_ids(
        np.array(vecs, dtype=np.float32),
        np.array(new_ids, dtype=np.uint64),
    )
    index.write(str(index_path))

    for map_key, entry in new_map_entries:
        chunk_map[map_key] = entry
    chunk_map_path.write_text(json.dumps(chunk_map, indent=2))

    print(f"[vectors] Indexed {len(new_ids)} model(s) -> {index_path}")


def query_index(
    text: str,
    fidelity_tier: str | None = None,
    analysis_type: str | None = None,
    solver_contract: str | None = None,
    top_k: int = 5,
    store_dir: str = "store",
    db_path: str | None = None,
) -> dict:
    """
    Semantic search over indexed model subsystems with optional post-filtering.
    Returns the same dict shape as the old ChromaDB implementation:
        {"ids": [[...]], "distances": [[...]], "metadatas": [[...]]}
    so query.py and all integration tests need zero changes.

    Post-filtering replaces ChromaDB where-clauses: fetches top_k*5 candidates
    then filters by metadata. At 6-100 models this is equivalent in practice.
    """
    index_path, chunk_map_path = _store_paths(store_dir)
    empty = {"ids": [[]], "distances": [[]], "metadatas": [[]]}

    if not index_path.exists():
        return empty

    chunk_map: dict = json.loads(chunk_map_path.read_text()) if chunk_map_path.exists() else {}

    id_to_meta: dict[int, dict] = {
        v["id"]: v
        for v in chunk_map.values()
        if v.get("source_type") == "model"
    }

    if not id_to_meta:
        return empty

    embed = _get_embed_model()
    q_vec = embed.encode([text], normalize_embeddings=True)[0].astype(np.float32)

    index = IdMapIndex.load(str(index_path))
    # Must fetch from entire index (knowledge chunks dilute model results).
    # Models can appear at rank 15-100+ in a mixed 800-entry index.
    fetch_k = min(top_k * 50, len(chunk_map))
    scores_mat, ids_mat = index.search(q_vec.reshape(1, -1), k=max(fetch_k, top_k))
    raw_ids, raw_dists = ids_mat[0], scores_mat[0]

    result_ids, result_dists, result_metas = [], [], []

    for chunk_id, dist in zip(raw_ids, raw_dists):
        meta = id_to_meta.get(int(chunk_id))
        if meta is None:
            continue  # knowledge chunk, not a model

        if fidelity_tier and meta.get("fidelity") != fidelity_tier:
            continue
        if analysis_type and meta.get("analysis") != analysis_type:
            continue
        if solver_contract and meta.get("solver") != solver_contract:
            continue

        result_ids.append(meta["model_id"])
        result_dists.append(float(dist))
        result_metas.append({
            "fidelity_tier":         meta.get("fidelity", ""),
            "analysis_type":         meta.get("analysis", ""),
            "solver_contract":       meta.get("solver", ""),
            "source_file":           meta.get("source_file", ""),
            "source_hash":           meta.get("source_hash", ""),
            "block_count":           meta.get("block_count", -1),
            "state_count":           meta.get("state_count", -1),
            "has_iron_loss_input":   meta.get("has_iron_loss_input", False),
            "has_copper_loss_input": meta.get("has_copper_loss_input", False),
            "output_domains":        meta.get("output_domains", ""),
            "input_domains":         meta.get("input_domains", ""),
        })

        if len(result_ids) >= top_k:
            break

    return {
        "ids":       [result_ids],
        "distances": [result_dists],
        "metadatas": [result_metas],
    }
