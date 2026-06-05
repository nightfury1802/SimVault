"""
Central path config for the KB pipeline. All paths from env vars.

Environment variables:
  SIMVAULT_GRAPHIFY_CACHE   path to graphify-out/cache/  (default: ../../graphify-out/cache)
  SIMVAULT_GRAPH_PATH       path to graphify-out/graph.json
  SIMVAULT_STORE_DIR        path to SimVault/store/  (default: ./store)
  SIMVAULT_LEAN_CTX_EXPORTS path to lean-ctx knowledge exports
  SIMVAULT_CLAUDE_LOGS      path to Claude Code JSONL session files
"""
import os
from pathlib import Path

_HERE = Path(__file__).parent.parent.parent          # SimVault/
_SIMSCAPE_ROOT = _HERE.parent                         # simscape-agent/

GRAPHIFY_CACHE_DIR = Path(os.environ.get(
    "SIMVAULT_GRAPHIFY_CACHE",
    str(_SIMSCAPE_ROOT / "graphify-out" / "cache")
))

GRAPH_PATH = Path(os.environ.get(
    "SIMVAULT_GRAPH_PATH",
    str(_SIMSCAPE_ROOT / "graphify-out" / "graph.json")
))

STORE_DIR = Path(os.environ.get(
    "SIMVAULT_STORE_DIR",
    str(_HERE / "store")
))

INDEX_PATH        = STORE_DIR / "kb.tq"
CHUNK_MAP_PATH    = STORE_DIR / "chunk_map.json"
EXPORT_STATE_PATH = STORE_DIR / ".export_state.json"

LEAN_CTX_EXPORTS_DIR = Path(os.environ.get(
    "SIMVAULT_LEAN_CTX_EXPORTS",
    str(Path.home() / ".config" / "lean-ctx" / "exports" / "knowledge")
))

CLAUDE_LOGS_DIR = Path(os.environ.get(
    "SIMVAULT_CLAUDE_LOGS",
    str(Path.home() / ".claude" / "projects" /
        "-Users-soorajkrishnan-simscape-agent")
))

MODEL_SPECS_DIR = _HERE / "kb" / "models"

EMBED_MODEL_NAME = "BAAI/bge-small-en-v1.5"
EMBED_DIM        = 384
