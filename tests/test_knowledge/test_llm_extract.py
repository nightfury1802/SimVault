"""Tests for LLM fact extraction from Claude Code session transcripts."""
import json


def test_parse_valid_response():
    from simvault.knowledge.llm_extract import parse_facts_response
    raw = json.dumps([
        {"type": "pitfall", "model_id": "MotorThermal11Node",
         "text": "Heat source polarity reversed", "confidence": 0.95},
    ])
    facts = parse_facts_response(raw)
    assert len(facts) == 1
    assert facts[0]["type"] == "pitfall"
    assert facts[0]["model_id"] == "MotorThermal11Node"


def test_parse_malformed_returns_empty():
    from simvault.knowledge.llm_extract import parse_facts_response
    assert parse_facts_response("not json") == []
    assert parse_facts_response("{}") == []


def test_parse_normalises_missing_model_id():
    from simvault.knowledge.llm_extract import parse_facts_response
    raw = json.dumps([{"type": "result", "text": "DOE 39/55 PASS", "confidence": 1.0}])
    facts = parse_facts_response(raw)
    assert facts[0]["model_id"] is None


def test_format_as_markdown():
    from simvault.knowledge.llm_extract import format_facts_as_markdown
    facts = [{"type": "pitfall", "model_id": "PMSM_FEM",
              "text": "Wrong voltage convention", "confidence": 0.9}]
    md = format_facts_as_markdown(facts, date="2026-06-05")
    assert "[pitfall]" in md
    assert "PMSM_FEM" in md
    assert "Wrong voltage convention" in md
    assert "2026-06-05" in md
