import json
import pytest
from pathlib import Path
STORE_DIR = Path(__file__).parent.parent / "store"
CROSS_EDGES_PATH = STORE_DIR / "cross_edges.json"
_skip = pytest.mark.skipif(not (STORE_DIR / "kb.tq").exists(),
                            reason="Run: simvault kb-update first")
@_skip
def test_model_spec_searchable():
    from simvault.retrieval.unified import UnifiedQuery
    results = UnifiedQuery().search("MotorThermal11Node thermal ports", k=10)
    combined = " ".join(r.get("source","") + r.get("text","") for r in results)
    assert "MotorThermal11Node" in combined
@pytest.mark.skipif(not CROSS_EDGES_PATH.exists(),
                    reason="Run: simvault kb-update first")
def test_cross_edges_exist():
    edges = json.loads(CROSS_EDGES_PATH.read_text()).get("edges", [])
    assert len(edges) > 0
    assert all("source" in e and "target" in e for e in edges)
def test_model_spec_tier_is_procedural():
    from simvault.memory.schema import infer_tier
    assert infer_tier("SimVault/kb/models/PMSM_FEM_PMSM_FEM.md") == "procedural"
def test_session_tier_is_episodic():
    from simvault.memory.schema import infer_tier
    assert infer_tier("store/sessions/2026-05-17.md") == "episodic"
def test_procedural_no_decay():
    from simvault.memory.scorer import effective_confidence
    from datetime import datetime, timedelta
    node = {"tier": "procedural", "confidence": 1.0,
            "created_at": (datetime.now()-timedelta(days=500)).isoformat()}
    assert effective_confidence(node) == 1.0
def test_no_contradiction_same_model_same_value():
    from simvault.memory.contradiction import find_contradictions
    existing = [{"id": "f1", "model_id": "PMSM_FEM",
                 "text": "T_ss = 107.63 Nm at 6000 RPM"}]
    # New fact confirms same numbers (107.63 Nm at 6000 RPM) → no contradiction
    new = {"model_id": "PMSM_FEM", "text": "steady state 107.63 Nm at 6000 RPM confirmed"}
    assert find_contradictions(new, existing) == []
def test_full_test_suite_still_passes():
    """The original 23 tests must still pass after all changes."""
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_integration.py", "-v", "--tb=short"],
        capture_output=True, text=True,
        cwd=str(Path(__file__).parent.parent)
    )
    assert result.returncode == 0, f"Original tests failed:\n{result.stdout}\n{result.stderr}"
