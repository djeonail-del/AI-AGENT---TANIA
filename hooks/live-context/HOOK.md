---
name: live-context
description: "Save conversation context in real-time on every message sent"
homepage: https://docs.openclaw.ai/automation/hooks
metadata:
  {"openclaw": {"emoji": "💬", "events": ["message:sent", "command:new", "command:reset"], "requires": {"bins": ["python3"]}}}
---

# Live Context Hook

Saves the last 30 messages to memory/last-conversation.md on every outbound message and on /new or /reset commands. Ensures seamless context continuity across session resets.
