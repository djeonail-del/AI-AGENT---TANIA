#!/bin/bash
set -euo pipefail

# Only run in remote Claude Code web sessions.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

# Install Python dependencies used by the trading-bot code
# (httpx, pandas, numpy, pyarrow). Idempotent — pip skips already-satisfied.
if [ -f "trading-bot/requirements.txt" ]; then
  python3 -m pip install --quiet --disable-pip-version-check --root-user-action=ignore -r trading-bot/requirements.txt
fi

# Make trading-bot importable from repo root (for py_compile / ad-hoc checks).
echo 'export PYTHONPATH="${CLAUDE_PROJECT_DIR}/trading-bot:${PYTHONPATH:-}"' >> "$CLAUDE_ENV_FILE"
