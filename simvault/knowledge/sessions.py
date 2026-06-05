"""Parse Claude Code JSONL session files to extract engineering turns."""
import json
from pathlib import Path

from .config import CLAUDE_LOGS_DIR

_KEYWORDS = [
    "Simscape", "PMSM", "FOC", "IM", "IFOC", "thermal", "flux", "torque",
    "Simulink", "DriveUnit", "AMESim", "Motor-CAD", "pitfall", "validated",
    "error", "fix", "workaround", "blocked", "PASS", "FAIL",
]


def list_sessions() -> list[Path]:
    return sorted(
        CLAUDE_LOGS_DIR.glob("*.jsonl"),
        key=lambda p: p.stat().st_mtime, reverse=True
    )


def score_turn(content: str) -> int:
    return sum(1 for kw in _KEYWORDS if kw.lower() in content.lower())


def extract_top_turns(session_path: Path, n: int = 20) -> list[dict]:
    turns = []
    with session_path.open() as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") == "message":
                content = ""
                for block in entry.get("message", {}).get("content", []):
                    if isinstance(block, dict) and block.get("type") == "text":
                        content += block.get("text", "")
                    elif isinstance(block, str):
                        content += block
                if content:
                    turns.append({
                        "role": entry.get("message", {}).get("role", "unknown"),
                        "content": content[:2000],
                        "score": score_turn(content),
                    })
    return sorted(turns, key=lambda t: t["score"], reverse=True)[:n]
