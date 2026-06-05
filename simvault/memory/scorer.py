from datetime import datetime
from .schema import TIER_DEFAULTS, MemoryTier


def effective_confidence(node: dict) -> float:
    if node.get("superseded_by"):
        return 0.0

    valid_until = node.get("valid_until")
    if valid_until:
        try:
            if datetime.fromisoformat(valid_until) < datetime.now():
                return 0.0
        except ValueError:
            pass

    try:
        tier = MemoryTier(node.get("tier", "episodic"))
    except ValueError:
        tier = MemoryTier.EPISODIC

    base = node.get("confidence", TIER_DEFAULTS[tier]["initial_confidence"])
    decay_days = TIER_DEFAULTS[tier]["decay_days"]

    if decay_days is None:
        return base

    created_str = node.get("created_at")
    if not created_str:
        return base

    try:
        age_days = (datetime.now() - datetime.fromisoformat(created_str)).days
    except ValueError:
        return base

    return round(base * max(0.05, 1.0 - (age_days / decay_days) * 0.5), 4)
