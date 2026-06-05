def _kb_graph():
    return {"nodes": [
        {"id": "s1", "label": "PMSM 11-Node Thermal Model session debrief",
         "source_file": "logs/session_2026-04-12.md"},
        {"id": "s2", "label": "MotorThermal11Node heat source polarity reversed pitfall",
         "source_file": "logs/session_2026-04-12.md"},
        {"id": "s3", "label": "FOCController voltage clamp fix", "source_file": "logs/x.md"},
        {"id": "s4", "label": "Julia setup", "source_file": "README.md"},
    ], "edges": []}


def test_finds_by_label():
    from simvault.graph.link_entities import find_kb_nodes_mentioning
    matches = find_kb_nodes_mentioning("MotorThermal11Node", _kb_graph())
    ids = [m["id"] for m in matches]
    assert "s2" in ids
    assert "s4" not in ids


def test_build_cross_edges():
    from simvault.graph.link_entities import build_cross_edges
    edges = build_cross_edges(["MotorThermal11Node", "FOCController"], _kb_graph())
    assert len(edges) > 0
    for e in edges:
        assert e["relation"] == "discusses_model"
        assert 0 < e["confidence"] <= 1.0


def test_no_duplicate_edges():
    from simvault.graph.link_entities import build_cross_edges
    edges = build_cross_edges(["MotorThermal11Node"], _kb_graph())
    pairs = [(e["source"], e["target"]) for e in edges]
    assert len(pairs) == len(set(pairs))
