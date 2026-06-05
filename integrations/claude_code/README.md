# Claude Code Integration

Registers a Stop hook that runs `simvault kb-update` after every Claude Code session,
keeping the KB index current with session logs, pitfalls, and validated results.

## Install

Add to `~/.claude/settings.json`:

```json
"Stop": [
  {
    "matcher": "",
    "hooks": [
      {
        "type": "command",
        "command": "/Users/soorajkrishnan/simscape-agent/SimVault/integrations/claude_code/stop_hook.sh"
      }
    ]
  }
]
```

## What it does

Runs on every Claude Code session stop:
1. Exports lean-ctx knowledge atoms → `store/sessions/`
2. Extracts engineering facts via LLM → `store/sessions/*-llm.md`
3. Runs graphify update (if not `--skip-graphify`)
4. Builds cross-edges model ↔ KB
5. Indexes knowledge chunks into turbovec

Logs to `store/kb_pipeline.log`.
