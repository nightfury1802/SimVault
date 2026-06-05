import pytest
from pathlib import Path

STORE_DIR = Path(__file__).parent.parent.parent / "store"


@pytest.mark.skipif(
    not (STORE_DIR / "kb.tq").exists(),
    reason="Run: simvault kb-update first"
)
def test_thermal_model_searchable():
    from simvault.knowledge.query_kb import semantic_search
    results = semantic_search("PMSM 11-node thermal model", k=10)
    combined = " ".join(r.get("source", "") + r.get("text", "") for r in results)
    assert "MotorThermal11Node" in combined


@pytest.mark.skipif(
    not (STORE_DIR / "kb.tq").exists(),
    reason="Run: simvault kb-update first"
)
def test_foc_model_searchable():
    from simvault.knowledge.query_kb import semantic_search
    results = semantic_search("field oriented control drive cycle", k=10)
    combined = " ".join(r.get("source", "") + r.get("text", "") for r in results)
    assert "FOCController" in combined or "FEM_IM_FOC" in combined
