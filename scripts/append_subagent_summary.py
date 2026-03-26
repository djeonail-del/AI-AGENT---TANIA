#!/usr/bin/env python3
"""
append_subagent_summary.py — Append a subagent work summary to today's daily notes.

Subagents should call this at the end of their work to ensure their output is
captured in memory/YYYY-MM-DD.md, surviving /new session resets.

Usage:
    python3 scripts/append_subagent_summary.py "Built X feature: ..." --agent "session-indexer"
    echo "Did something important" | python3 scripts/append_subagent_summary.py --agent "my-agent"
    python3 scripts/append_subagent_summary.py --agent "coder" << 'EOF'
    Multi-line
    summary here
    EOF
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path


def _detect_workspace() -> str:
    if os.environ.get("OPENCLAW_WORKSPACE"):
        return os.environ["OPENCLAW_WORKSPACE"]
    if Path("/Users/mac/.openclaw/workspace").exists():
        return "/Users/mac/.openclaw/workspace"
    return str(Path(__file__).parent.parent)


WORKSPACE_DIR = _detect_workspace()
MEMORY_DIR = os.path.join(WORKSPACE_DIR, "memory")


def main():
    parser = argparse.ArgumentParser(
        description="Append a subagent work summary to today's daily memory file."
    )
    parser.add_argument(
        "summary",
        nargs="?",
        default=None,
        help="Summary text (or omit to read from stdin)",
    )
    parser.add_argument(
        "--agent",
        default="subagent",
        help="Agent name/identifier (default: subagent)",
    )
    args = parser.parse_args()

    # Get summary from argument or stdin
    if args.summary:
        summary = args.summary.strip()
    elif not sys.stdin.isatty():
        summary = sys.stdin.read().strip()
    else:
        print("ERROR: Provide summary as argument or via stdin.", file=sys.stderr)
        print("Usage: python3 scripts/append_subagent_summary.py 'summary' --agent 'name'", file=sys.stderr)
        sys.exit(1)

    if not summary:
        print("ERROR: Summary is empty.", file=sys.stderr)
        sys.exit(1)

    # Ensure memory dir exists
    os.makedirs(MEMORY_DIR, exist_ok=True)

    # Build the block to append
    today = datetime.now().strftime("%Y-%m-%d")
    now_str = datetime.now().strftime("%H:%M")
    daily_file = os.path.join(MEMORY_DIR, f"{today}.md")

    block = (
        f"\n## 🤖 Subagent Work: {args.agent} ({now_str})\n"
        f"{summary}\n"
    )

    with open(daily_file, "a", encoding="utf-8") as f:
        f.write(block)

    print(f"✅ Appended summary for [{args.agent}] to {daily_file}")


if __name__ == "__main__":
    main()
