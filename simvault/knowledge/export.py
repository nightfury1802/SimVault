"""Export lean-ctx knowledge atoms to store/sessions/YYYY-MM-DD.md."""
import json
from datetime import datetime
from pathlib import Path

from .config import LEAN_CTX_EXPORTS_DIR, STORE_DIR, EXPORT_STATE_PATH


def run() -> int:
    exports = sorted(
        LEAN_CTX_EXPORTS_DIR.glob("knowledge-*.json"),
        key=lambda p: p.stat().st_mtime, reverse=True
    )
    if not exports:
        print("[export] No lean-ctx exports found.")
        return 0

    try:
        data = json.loads(exports[0].read_text())
    except (json.JSONDecodeError, OSError) as e:
        print(f"[export] Could not read export: {e}")
        return 0

    state = json.loads(EXPORT_STATE_PATH.read_text()) if EXPORT_STATE_PATH.exists() else {}
    exported_keys = set(state.get("exported_keys", []))

    facts = data.get("facts", data.get("knowledge", []))
    new_facts = [f for f in facts if f.get("key") not in exported_keys]

    if not new_facts:
        print("[export] No new facts.")
        return 0

    sessions_dir = STORE_DIR / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    out = sessions_dir / f"{today}.md"

    lines = [f"# Session Knowledge — {today}\n"]
    for fact in new_facts:
        lines.append(
            f"## [{fact.get('category', 'general')}] {fact.get('key', '')}\n"
            f"{fact.get('value', fact.get('text', ''))}\n"
        )
    out.write_text("\n".join(lines))

    exported_keys.update(f.get("key") for f in new_facts)
    state["exported_keys"] = list(exported_keys)
    EXPORT_STATE_PATH.write_text(json.dumps(state, indent=2))
    print(f"[export] {len(new_facts)} fact(s) → {out}")
    return len(new_facts)
