def test_classify_model_query():
    from simvault.retrieval.unified import classify_unified_query
    assert classify_unified_query("MotorThermal11Node ports and pitfalls") == "model+kb"

def test_classify_kb_query():
    from simvault.retrieval.unified import classify_unified_query
    assert classify_unified_query("flux weakening double Clarke pitfall") == "kb"

def test_classify_relationship():
    from simvault.retrieval.unified import classify_unified_query
    assert classify_unified_query("how does FOCController connect to CRT") == "relationship"

def test_result_structure():
    from simvault.retrieval.unified import UnifiedQuery
    uq = UnifiedQuery()
    results = uq.search("test xyz", k=5)
    assert isinstance(results, list)
