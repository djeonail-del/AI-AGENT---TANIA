#!/usr/bin/env python3
"""Patch models.json to enable vision for ollama vision models"""
import json, os, sys, re

VISION_MODELS = ["kimi-k2.5:cloud", "qwen3-vl", "qwen3.5", "qwen2.5vl", "llava", "minicpm-v", "moondream", "glm-ocr", "glm"]

path = os.path.expanduser('~/.openclaw/agents/main/agent/models.json')
if not os.path.exists(path):
    sys.exit(0)

with open(path) as f:
    d = json.load(f)

patched = False
for pname, pdata in d.get('providers', {}).items():
    if 'ollama' in pname.lower():
        for model in pdata.get('models', []):
            mid = model.get('id', '').lower()
            is_vision = any(v in mid for v in VISION_MODELS)
            if is_vision and model.get('input') != ['text', 'image']:
                model['input'] = ['text', 'image']
                patched = True
                print(f'✅ Patched {model["id"]} → text+image')

if patched:
    with open(path, 'w') as f:
        json.dump(d, f, indent=2)
else:
    print('ℹ️ Nothing to patch')
