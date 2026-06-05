def test_merges_lists():
    from simvault.retrieval.rrf import reciprocal_rank_fusion
    l1 = [{"id": "a", "score": 0.9}, {"id": "b", "score": 0.8}]
    l2 = [{"id": "b", "score": 0.95}, {"id": "c", "score": 0.7}]
    merged = reciprocal_rank_fusion([l1, l2])
    assert {r["id"] for r in merged} == {"a", "b", "c"}


def test_shared_ranks_higher():
    from simvault.retrieval.rrf import reciprocal_rank_fusion
    l1 = [{"id": "shared"}, {"id": "only1"}]
    l2 = [{"id": "shared"}, {"id": "only2"}]
    merged = reciprocal_rank_fusion([l1, l2])
    assert merged[0]["id"] == "shared"


def test_empty():
    from simvault.retrieval.rrf import reciprocal_rank_fusion
    assert reciprocal_rank_fusion([[], []]) == []
