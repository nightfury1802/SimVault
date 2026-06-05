import json
from pathlib import Path
from rank_bm25 import BM25Okapi


class BM25Index:
    def __init__(self, chunks: list[dict]):
        self._chunks = chunks
        tokenized = [c["text"].lower().split() for c in chunks]
        self._bm25 = BM25Okapi(tokenized) if tokenized else None

    def search(self, query: str, k: int = 10) -> list[dict]:
        if not self._bm25 or not self._chunks:
            return []
        scores = self._bm25.get_scores(query.lower().split())
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        return [
            {
                "id": self._chunks[i]["id"],
                "score": float(s),
                "source": self._chunks[i].get("source", ""),
                "text": self._chunks[i].get("text", "")[:300],
                "mode": "bm25",
            }
            for i, s in ranked[:k]
            if s > 0
        ]

    @classmethod
    def from_chunk_map(cls, chunk_map: dict, cache_dir: Path) -> "BM25Index":
        chunks = []
        for rel_path, meta in chunk_map.items():
            if meta.get("source_type") == "model":
                continue  # model entries embedded differently
            chunk_file = cache_dir / rel_path
            if not chunk_file.exists():
                continue
            try:
                data = json.loads(chunk_file.read_text())
            except Exception:
                continue
            text = " ".join(n.get("label", "") for n in data.get("nodes", [])).strip()
            if text:
                chunks.append({"id": str(meta["id"]), "text": text, "source": rel_path})
        return cls(chunks)
