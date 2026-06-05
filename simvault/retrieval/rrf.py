def reciprocal_rank_fusion(
    result_lists: list[list[dict]], k: int = 60
) -> list[dict]:
    """Merge ranked lists with RRF. Each result needs 'id' field."""
    if not result_lists:
        return []
    scores: dict[str, float] = {}
    meta: dict[str, dict] = {}
    for results in result_lists:
        for rank, r in enumerate(results):
            doc_id = r["id"]
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
            if doc_id not in meta:
                meta[doc_id] = {kk: v for kk, v in r.items() if kk != "score"}
    return sorted(
        [
            {**meta[doc_id], "score": round(score, 6)}
            for doc_id, score in scores.items()
        ],
        key=lambda x: x["score"],
        reverse=True,
    )
