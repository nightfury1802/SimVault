"""Verify the new turbovec-backed query_index() returns the same shape as before."""
import json
import pytest
from pathlib import Path

_ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="session")
def built_index():
    """Requires simvault index to have been run."""
    store = _ROOT / "store"
    return store.exists() and (store / "kb.tq").exists()


def test_query_index_return_shape(built_index):
    """query_index() must return {"ids":[[...]], "distances":[[...]], "metadatas":[[...]]}"""
    if not built_index:
        pytest.skip("Run: simvault index examples/pmsm_drive/ first")
    from simvault.vectors.index import query_index
    result = query_index("PMSM motor", top_k=3, store_dir=str(_ROOT / "store"))
    assert "ids" in result and isinstance(result["ids"], list)
    assert "distances" in result and isinstance(result["distances"], list)
    assert "metadatas" in result and isinstance(result["metadatas"], list)
    assert len(result["ids"]) == 1       # outer list wrapping
    assert len(result["distances"]) == 1
    assert len(result["metadatas"]) == 1


def test_fidelity_post_filter(built_index):
    """Detailed filter must not return simplified models."""
    if not built_index:
        pytest.skip("Run: simvault index examples/pmsm_drive/ first")
    from simvault.vectors.index import query_index
    result = query_index("PMSM motor", fidelity_tier="detailed", top_k=5,
                         store_dir=str(_ROOT / "store"))
    metas = result["metadatas"][0]
    for m in metas:
        assert m.get("fidelity_tier") == "detailed", \
            f"Non-detailed model leaked through: {m}"


def test_analysis_post_filter(built_index):
    """Analysis type filter must exclude non-matching models."""
    if not built_index:
        pytest.skip("Run: simvault index examples/pmsm_drive/ first")
    from simvault.vectors.index import query_index
    result = query_index("motor", analysis_type="thermal", top_k=5,
                         store_dir=str(_ROOT / "store"))
    metas = result["metadatas"][0]
    for m in metas:
        assert m.get("analysis_type") == "thermal", \
            f"Non-thermal model leaked through: {m}"
