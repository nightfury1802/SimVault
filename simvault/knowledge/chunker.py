"""
Built-in text chunker for users without graphify.
Scans a directory for text files, splits into ~1500-char chunks,
writes JSON files compatible with indexer.py to store/chunks/.
"""
import json
import hashlib
from pathlib import Path

SUPPORTED = {".md", ".py", ".jl", ".m", ".yaml", ".yml", ".txt"}
CHUNK_SIZE = 1500
OVERLAP = 200


def _chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = OVERLAP) -> list[str]:
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        chunks.append(text[start:end])
        start += size - overlap
    return chunks


def chunk_directory(root: Path, output_dir: Path) -> int:
    """Chunk all text files under root, write JSON chunks to output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for path in sorted(root.rglob("*")):
        if path.suffix not in SUPPORTED or not path.is_file():
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        chunks = _chunk_text(text)
        rel = path.relative_to(root)
        for i, chunk in enumerate(chunks):
            chunk_id = hashlib.md5(f"{rel}:{i}".encode()).hexdigest()[:12]
            out = output_dir / f"{chunk_id}.json"
            out.write_text(json.dumps({
                "nodes": [{
                    "id": chunk_id,
                    "label": chunk[:200],
                    "source_file": str(rel),
                }],
                "edges": [],
            }))
            count += 1
    print(f"[chunker] {count} chunks → {output_dir}")
    return count
