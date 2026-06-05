import pytest
from pathlib import Path


def test_path_to_id_stable():
    from simvault.knowledge.indexer import path_to_id
    assert path_to_id("cache/ast/foo.json") == path_to_id("cache/ast/foo.json")


def test_path_to_id_unique():
    from simvault.knowledge.indexer import path_to_id
    assert path_to_id("a.json") != path_to_id("b.json")


def test_extract_text_concatenates_labels():
    from simvault.knowledge.indexer import extract_text
    chunk = {
        "nodes": [
            {"id": "n1", "label": "MotorThermal11Node pitfall", "source_file": "logs/s.md"},
            {"id": "n2", "label": "temperature_K output"},
        ]
    }
    text = extract_text(chunk)
    assert "MotorThermal11Node pitfall" in text
    assert "temperature_K output" in text


def test_extract_text_empty():
    from simvault.knowledge.indexer import extract_text
    assert extract_text({}) == ""
    assert extract_text({"nodes": []}) == ""
