from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class MemoryTier(str, Enum):
    WORKING    = "working"     # raw observations, decay 7 days
    EPISODIC   = "episodic"    # session summaries, decay 90 days
    SEMANTIC   = "semantic"    # validated facts, permanent
    PROCEDURAL = "procedural"  # model specs + workflows, permanent


TIER_DEFAULTS = {
    MemoryTier.WORKING:    {"decay_days": 7,    "initial_confidence": 0.60},
    MemoryTier.EPISODIC:   {"decay_days": 90,   "initial_confidence": 0.75},
    MemoryTier.SEMANTIC:   {"decay_days": None,  "initial_confidence": 1.00},
    MemoryTier.PROCEDURAL: {"decay_days": None,  "initial_confidence": 1.00},
}


@dataclass
class MemoryNode:
    id: str
    label: str
    tier: MemoryTier
    confidence: Optional[float] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_validated: Optional[str] = None
    superseded_by: Optional[str] = None
    valid_until: Optional[str] = None
    namespace: str = "default"
    source_file: Optional[str] = None

    def __post_init__(self):
        if self.confidence is None:
            self.confidence = TIER_DEFAULTS[self.tier]["initial_confidence"]


_TIER_RULES: list[tuple[list[str], str]] = [
    (["SimVault/kb/models/", "kb/models/"],      "procedural"),
    (["PLAN.md", "docs/PLAN", "/decisions"],      "semantic"),
    (["store/sessions/", "kb/sessions/"],          "episodic"),
    (["logs/session_", "logs/session"],            "episodic"),
    ([".jl", ".m", ".py"],                         "procedural"),
    (["skills/", "SKILL.md"],                      "procedural"),
]


def infer_tier(source_file: str) -> str:
    for patterns, tier in _TIER_RULES:
        if any(pat in source_file for pat in patterns):
            return tier
    return MemoryTier.EPISODIC.value
