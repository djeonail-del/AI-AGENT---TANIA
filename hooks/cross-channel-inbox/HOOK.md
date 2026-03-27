---
name: cross-channel-inbox
description: "Track incoming messages from all channels in real-time for cross-channel awareness"
homepage: https://docs.openclaw.ai/automation/hooks
metadata:
  {"openclaw": {"emoji": "📥", "events": ["message:received"], "requires": {"bins": ["python3"]}}}
---

# Cross-Channel Inbox Hook

On every incoming message, extracts channel metadata and appends to memory/cross-channel-inbox.md.
This gives Tania real-time awareness of messages from other channels (e.g. Discord) while active in Telegram.
