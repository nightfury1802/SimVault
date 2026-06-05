def test_flags_different_numbers_same_model():
    from simvault.memory.contradiction import find_contradictions
    existing = [{"id": "f1", "model_id": "PMSM_FEM",
                 "text": "T_ss = 107.63 Nm at 6000 RPM", "type": "result"}]
    new = {"model_id": "PMSM_FEM", "text": "T_ss = 112.4 Nm at 6000 RPM", "type": "result"}
    c = find_contradictions(new, existing)
    assert len(c) == 1 and c[0]["existing_id"] == "f1"


def test_no_contradiction_different_models():
    from simvault.memory.contradiction import find_contradictions
    existing = [{"id": "f1", "model_id": "PMSM_FEM", "text": "T_ss = 107.63 Nm"}]
    new = {"model_id": "FEM_IM", "text": "T_ss = 107.63 Nm"}
    assert find_contradictions(new, existing) == []


def test_no_contradiction_same_numbers():
    from simvault.memory.contradiction import find_contradictions
    existing = [{"id": "f1", "model_id": "PMSM_FEM", "text": "T_ss = 107.63 Nm"}]
    new = {"model_id": "PMSM_FEM", "text": "steady state 107.63 Nm confirmed"}
    assert find_contradictions(new, existing) == []


def test_contradiction_has_reason():
    from simvault.memory.contradiction import find_contradictions
    existing = [{"id": "f1", "model_id": "PMSM_FEM", "text": "T_ss = 107.63 Nm"}]
    new = {"model_id": "PMSM_FEM", "text": "T_ss = 115.0 Nm"}
    c = find_contradictions(new, existing)
    assert "reason" in c[0]
