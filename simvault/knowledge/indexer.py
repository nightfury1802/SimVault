"""
Incremental turbovec indexer for graphify cache chunks (knowledge layer).
Writes to the same store/kb.tq and store/chunk_map.json as vectors/index.py.
Model entries (source_type='model') are not touched.
"""
import hashlib
import json
from pathlib import Path
from typing import Optional

import numpy as np
from sentence_transformers import SentenceTransformer
from turbovec import IdMapIndex

from .config import (
    GRAPHIFY_CACHE_DIR, STORE_DIR, INDEX_PATH, CHUNK_MAP_PATH,
    EMBED_MODEL_NAME, EMBED_DIM
)


def path_to_id(rel_path: str) -> int:
    return int(hashlib.md5(rel_path.encode()).hexdigest()[:16], 16) % (2**63)


def extract_text(chunk_data: dict) -> str:
    parts = []
    for node in chunk_data.get("nodes", []):
        label = node.get("label") or node.get("id") or ""
        source = node.get("source_file") or ""
        if label:
            parts.append(label)
        if source and source not in parts:
            parts.append(f"[{source}]")
    return " | ".join(parts)


def run(cache_dir: Optional[Path] = None) -> int:
    """
    Scan cache_dir for .json chunks, embed new/changed ones into store/kb.tq.
    Skips entries with source_type='model' (managed by vectors/index.py).
    Returns count of newly embedded chunks.
    """
    cache_dir = cache_dir or GRAPHIFY_CACHE_DIR
    if not cache_dir.exists():
        print(f"[indexer] Cache dir not found: {cache_dir}")
        return 0

    chunk_map: dict = json.loads(CHUNK_MAP_PATH.read_text()) if CHUNK_MAP_PATH.exists() else {}

    chunk_files = sorted(cache_dir.rglob("*.json"))
    new_texts, new_ids, new_entries = [], [], []

    for chunk_file in chunk_files:
        rel = str(chunk_file.relative_to(cache_dir.parent))
        mtime = chunk_file.stat().st_mtime
        stored = chunk_map.get(rel, {})
        if stored.get("source_type") == "model":
            continue  # managed by vectors/index.py
        if stored.get("mtime") == mtime:
            continue
        try:
            data = json.loads(chunk_file.read_text())
        except json.JSONDecodeError:
            continue
        text = extract_text(data)
        if not text.strip():
            continue
        chunk_id = path_to_id(rel)
        source_file = next(
            (n.get("source_file", "") for n in data.get("nodes", [])), ""
        )
        new_texts.append(text)
        new_ids.append(chunk_id)
        new_entries.append((rel, mtime, chunk_id, source_file))

    if not new_texts:
        print(f"[indexer] No new knowledge chunks. Total: {len(chunk_map)}")
        return 0

    print(f"[indexer] Embedding {len(new_texts)} knowledge chunks...")
    model = SentenceTransformer(EMBED_MODEL_NAME)
    vecs = model.encode(new_texts, normalize_embeddings=True, show_progress_bar=False)

    STORE_DIR.mkdir(parents=True, exist_ok=True)
    if INDEX_PATH.exists():
        index = IdMapIndex.load(str(INDEX_PATH))
        for chunk_id in new_ids:
            index.remove(chunk_id)
    else:
        index = IdMapIndex(EMBED_DIM, bit_width=4)

    index.add_with_ids(
        np.array(vecs, dtype=np.float32),
        np.array(new_ids, dtype=np.uint64),
    )
    index.write(str(INDEX_PATH))

    for rel, mtime, chunk_id, source_file in new_entries:
        chunk_map[rel] = {
            "id": chunk_id,
            "mtime": mtime,
            "source_type": "knowledge",
            "tier": "episodic",
            "source_file": source_file,
        }
    CHUNK_MAP_PATH.write_text(json.dumps(chunk_map, indent=2))
    print(f"[indexer] Done. Total: {len(chunk_map)}")
    return len(new_texts)
