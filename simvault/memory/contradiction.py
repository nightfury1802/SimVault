import json
import re
from difflib import SequenceMatcher
from pathlib import Path

from ..knowledge.config import STORE_DIR

CONTRADICTIONS_PATH = STORE_DIR / "contradictions.json"


def _nums(text: str) -> set[float]:
    """Extract all floating-point numbers from text."""
    result = set()
    for m in re.findall(r"\d+\.?\d*", text):
        try:
            result.add(float(m))
        except ValueError:
            pass
    return result


def find_contradictions(
    new_fact: dict,
    existing: list[dict],
    threshold: float = 0.45,
) -> list[dict]:
    """
    Detect contradictions between new fact and existing facts for same model.

    A contradiction is detected when:
    1. Both facts reference the same model_id
    2. The text similarity is above threshold (0.45)
    3. The facts contain different numbers

    Args:
        new_fact: dict with keys: model_id, text, type (optional)
        existing: list of fact dicts with keys: id, model_id, text, type
        threshold: text similarity threshold (SequenceMatcher ratio)

    Returns:
        list of contradiction dicts with keys: existing_id, similarity, reason
    """
    new_nums = _nums(new_fact.get("text", ""))
    out = []

    for fact in existing:
        # Only compare facts from same model
        if fact.get("model_id") != new_fact.get("model_id"):
            continue

        old_nums = _nums(fact.get("text", ""))

        # No contradiction if either text has no numbers or numbers match
        if not new_nums or not old_nums or new_nums == old_nums:
            continue

        # Compute text similarity
        sim = SequenceMatcher(
            None,
            new_fact.get("text", "").lower(),
            fact.get("text", "").lower()
        ).ratio()

        # Only flag if similarity is high enough
        if sim < threshold:
            continue

        out.append({
            "existing_id": fact["id"],
            "similarity": round(sim, 3),
            "reason": f"Numbers differ: existing={sorted(old_nums)} new={sorted(new_nums)}",
        })

    return out


def save_contradiction(c: dict) -> None:
    """Save a contradiction record to the store."""
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    existing = (
        json.loads(CONTRADICTIONS_PATH.read_text())
        if CONTRADICTIONS_PATH.exists()
        else []
    )
    existing.append(c)
    CONTRADICTIONS_PATH.write_text(json.dumps(existing, indent=2))
