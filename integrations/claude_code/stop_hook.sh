#!/usr/bin/env bash
# Claude Code Stop hook — run after every session to keep KB current.
cd /Users/soorajkrishnan/simscape-agent/SimVault
simvault kb-update >> store/kb_pipeline.log 2>&1
exit 0
