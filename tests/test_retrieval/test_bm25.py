def test_exact_match_scores_high():
    from simvault.retrieval.bm25 import BM25Index
    chunks = [
        {"id": "c1", "text": "MotorThermal11Node heat source loss_copper_W input node", "source": "x"},
        {"id": "c2", "text": "PMSM field oriented control d-axis q-axis reference", "source": "y"},
        {"id": "c3", "text": "PMSM motor inverter architecture design", "source": "z"},
    ]
    idx = BM25Index(chunks)
    results = idx.search("MotorThermal11Node", k=3)
    assert len(results) > 0
    assert results[0]["id"] == "c1"


def test_no_match_returns_empty():
    from simvault.retrieval.bm25 import BM25Index
    idx = BM25Index([{"id": "c1", "text": "flux weakening", "source": "x"}])
    assert idx.search("xyz_nonexistent_abc", k=3) == []


def test_ranking_by_frequency():
    from simvault.retrieval.bm25 import BM25Index
    chunks = [
        {"id": "c1", "text": "PMSM PMSM PMSM motor thermal", "source": "a"},
        {"id": "c2", "text": "PMSM motor inverter", "source": "b"},
        {"id": "c3", "text": "induction machine drive", "source": "c"},
    ]
    idx = BM25Index(chunks)
    results = idx.search("PMSM motor", k=2)
    assert len(results) > 0
    assert results[0]["id"] == "c1"
