"""Vector store indexer: embed model/subsystem summaries into ChromaDB."""
from __future__ import annotations

import json
from glob import glob
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

_MODEL_NAME = "BAAI/bge-small-en-v1.5"
_COLLECTION = "simvault"

_embed_model: SentenceTransformer | None = None


def _get_embed_model() -> SentenceTransformer:
    global _embed_model
    if _embed_model is None:
        _embed_model = SentenceTransformer(_MODEL_NAME)
    return _embed_model


def _get_client(db_path: str) -> chromadb.ClientAPI:
    return chromadb.PersistentClient(path=db_path)


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
    """Build a rich text embedding document from subsystem metadata."""
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


def build_index(canonicalized_dir: str, db_path: str = ".svdb") -> None:
    """Index all JSON files in canonicalized_dir into ChromaDB."""
    client = _get_client(db_path)
    collection = client.get_or_create_collection(
        _COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )
    embed = _get_embed_model()

    files = sorted(glob(f"{canonicalized_dir}/*.json"))
    if not files:
        print(f"No JSON files in {canonicalized_dir}")
        return

    ids, docs, metas = [], [], []

    for json_file in files:
        meta = json.loads(Path(json_file).read_text())
        for subsystem in meta.get("subsystems", []):
            ss_id = subsystem["id"]
            tags = subsystem.get("tags", {})

            # Incremental: skip if source_hash unchanged
            try:
                existing = collection.get(ids=[ss_id], include=["metadatas"])
                if existing["ids"] and existing["metadatas"][0].get("source_hash") == subsystem.get("source_hash"):
                    continue
            except Exception:
                pass

            doc = _build_doc(subsystem)
            meta_dict = {
                "fidelity_tier":          tags.get("fidelity_tier", "unknown"),
                "analysis_type":          tags.get("analysis_type", "unknown"),
                "solver_contract":        tags.get("solver_contract", "continuous"),
                "source_file":            subsystem.get("source_file", ""),
                "source_hash":            subsystem.get("source_hash", ""),
                "block_count":            subsystem.get("block_count", -1),
                "state_count":            subsystem.get("state_count", -1),
                "has_iron_loss_input":    _has_port(subsystem, "loss_iron_W",   "input"),
                "has_copper_loss_input":  _has_port(subsystem, "loss_copper_W", "input"),
                "output_domains":         ",".join(_output_domains(subsystem)),
                "input_domains":          ",".join(_input_domains(subsystem)),
            }
            ids.append(ss_id)
            docs.append(doc)
            metas.append(meta_dict)

    if not ids:
        print("All entries up to date — nothing to index.")
        return

    # Batch embed
    embeddings = embed.encode(docs, normalize_embeddings=True).tolist()

    collection.upsert(ids=ids, documents=docs, metadatas=metas, embeddings=embeddings)
    print(f"Indexed {len(ids)} subsystem(s) into {db_path}")


def query_index(
    text: str,
    fidelity_tier: str | None = None,
    analysis_type: str | None = None,
    solver_contract: str | None = None,
    top_k: int = 5,
    db_path: str = ".svdb",
) -> dict:
    """Semantic search over indexed subsystems."""
    client = _get_client(db_path)
    collection = client.get_or_create_collection(_COLLECTION)
    embed = _get_embed_model()

    query_vec = embed.encode([text], normalize_embeddings=True).tolist()

    where: dict = {}
    if fidelity_tier:
        where["fidelity_tier"] = {"$eq": fidelity_tier}
    if analysis_type:
        where["analysis_type"] = {"$eq": analysis_type}
    if solver_contract:
        where["solver_contract"] = {"$eq": solver_contract}

    kwargs: dict = {
        "query_embeddings": query_vec,
        "n_results": min(top_k, collection.count() or 1),
        "include": ["documents", "metadatas", "distances"],
    }
    if where:
        kwargs["where"] = where

    return collection.query(**kwargs)
