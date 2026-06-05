def test_classify_content():
    from simvault.knowledge.query_kb import classify_query
    assert classify_query("flux weakening pitfall IFOC") == "content"


def test_classify_relationship():
    from simvault.knowledge.query_kb import classify_query
    assert classify_query("how does FOCController connect to CRT") == "relationship"


def test_classify_model_trigger():
    from simvault.knowledge.query_kb import classify_query, SIMVAULT_MODEL_IDS
    assert "MotorThermal11Node" in SIMVAULT_MODEL_IDS
    assert "PMSM_FEM" in SIMVAULT_MODEL_IDS
    assert classify_query("MotorThermal11Node pitfalls") == "model"
