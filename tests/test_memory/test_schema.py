def test_tiers_exist():
    from simvault.memory.schema import MemoryTier
    assert MemoryTier.WORKING.value == "working"
    assert MemoryTier.EPISODIC.value == "episodic"
    assert MemoryTier.SEMANTIC.value == "semantic"
    assert MemoryTier.PROCEDURAL.value == "procedural"

def test_node_defaults():
    from simvault.memory.schema import MemoryNode, MemoryTier
    from datetime import datetime
    node = MemoryNode(id="x", label="y", tier=MemoryTier.PROCEDURAL)
    assert node.confidence == 1.0
    assert node.namespace == "default"
    assert node.superseded_by is None
    datetime.fromisoformat(node.created_at)  # must be valid ISO

def test_infer_tier_model_spec():
    from simvault.memory.schema import infer_tier
    assert infer_tier("SimVault/kb/models/PMSM_FEM_PMSM_FEM.md") == "procedural"

def test_infer_tier_session_log():
    from simvault.memory.schema import infer_tier
    assert infer_tier("logs/session_2026-04-12.md") == "episodic"
    assert infer_tier("store/sessions/2026-05-17.md") == "episodic"

def test_infer_tier_plan_doc():
    from simvault.memory.schema import infer_tier
    assert infer_tier("docs/PLAN.md") == "semantic"

def test_infer_tier_source_code():
    from simvault.memory.schema import infer_tier
    assert infer_tier("src/control/FOCController.jl") == "procedural"
