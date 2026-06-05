import os
from pathlib import Path


def test_default_paths_are_path_objects(monkeypatch):
    monkeypatch.delenv("SIMVAULT_GRAPHIFY_CACHE", raising=False)
    monkeypatch.delenv("SIMVAULT_STORE_DIR", raising=False)
    import importlib
    import simvault.knowledge.config as cfg
    importlib.reload(cfg)
    assert isinstance(cfg.GRAPHIFY_CACHE_DIR, Path)
    assert isinstance(cfg.STORE_DIR, Path)
    assert isinstance(cfg.INDEX_PATH, Path)
    assert isinstance(cfg.CHUNK_MAP_PATH, Path)


def test_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMVAULT_STORE_DIR", str(tmp_path / "store"))
    import importlib
    import simvault.knowledge.config as cfg
    importlib.reload(cfg)
    assert cfg.STORE_DIR == tmp_path / "store"
    assert cfg.INDEX_PATH == tmp_path / "store" / "kb.tq"
