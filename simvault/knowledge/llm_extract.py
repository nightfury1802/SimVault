"""
LLM fact extraction from Claude Code session transcripts.
Uses claude-haiku-4-5-20251001. No API call in tests — parse/format functions are pure.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import anthropic

from .config import STORE_DIR
from .sessions import extract_top_turns, list_sessions

_PROMPT = """\
Extract engineering facts from this simulation modeling session.
Return ONLY a JSON array — no other text:
[{{"type":"pitfall"|"result"|"decision"|"model_ref",
   "model_id":"<SimVault ID or null>",
   "text":"<one concise sentence>",
   "confidence":<0.0-1.0>}}]
Known model IDs: PMSM_FEM, PMSM_avg, MotorThermal11Node, FOCController, FEM_IM, FEM_IM_FOC_MA
confidence: 1.0=validated, 0.7-0.9=likely, 0.5-0.7=inferred
Return 5-15 high-quality facts only.
Conversation:
{conversation}"""


def parse_facts_response(raw: str) -> list[dict]:
    """Parse JSON array response from LLM. Returns normalized facts list."""
    try:
        data = json.loads(raw.strip())
    except json.JSONDecodeError:
        return []

    if not isinstance(data, list) or not data:
        return []

    return [
        {
            "type": item.get("type", "unknown"),
            "model_id": item.get("model_id", None),
            "text": str(item.get("text", "")),
            "confidence": float(item.get("confidence", 0.7)),
        }
        for item in data
        if isinstance(item, dict) and "text" in item
    ]


def format_facts_as_markdown(facts: list[dict], date: Optional[str] = None) -> str:
    """Format facts as markdown document."""
    date = date or datetime.now().strftime("%Y-%m-%d")
    lines = [
        f"# LLM-Extracted Facts — {date}\n",
        "_Auto-extracted by claude-haiku-4-5-20251001_\n",
    ]

    for f in facts:
        model_tag = f" [{f['model_id']}]" if f.get("model_id") else ""
        lines.append(
            f"## [{f['type']}]{model_tag} (conf={f.get('confidence', 0.7):.2f})\n{f['text']}\n"
        )

    return "\n".join(lines)


def extract_from_session(session_path: Path, n_turns: int = 20) -> list[dict]:
    """Extract facts from a single Claude Code session file."""
    turns = extract_top_turns(session_path, n=n_turns)
    if not turns:
        return []

    conversation = "\n\n".join(
        f"{t['role'].upper()}: {t['content'][:600]}" for t in turns
    )

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": _PROMPT.format(conversation=conversation)}],
        )
        return parse_facts_response(response.content[0].text)
    except Exception as e:
        print(f"[llm_extract] API call failed: {e}")
        return []


def run(session_path: Optional[Path] = None) -> int:
    """Run extraction on a session and save markdown to store/sessions/."""
    if session_path is None:
        sessions = list_sessions()
        if not sessions:
            print("[llm_extract] No sessions found.")
            return 0
        session_path = sessions[0]

    print(f"[llm_extract] Extracting from {session_path.name}...")
    facts = extract_from_session(session_path)

    if not facts:
        return 0

    date = datetime.now().strftime("%Y-%m-%d")
    out = STORE_DIR / "sessions" / f"{date}-llm.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(format_facts_as_markdown(facts, date=date))

    print(f"[llm_extract] {len(facts)} facts → {out}")
    return len(facts)
