#!/bin/bash
# Patch OpenClaw to enable vision for ollama vision models
# Run this after every openclaw update

FILE="/opt/homebrew/lib/node_modules/openclaw/dist/provider-models-BKjzpTsb.js"

if [ ! -f "$FILE" ]; then
    echo "❌ File not found: $FILE"
    exit 1
fi

python3 -c "
with open('$FILE', 'r') as f:
    content = f.read()

old = 'input: Array.isArray(model.tags) ? model.tags.includes(\"vision\") ? [\"text\", \"image\"] : [\"text\"] : fallback?.input ?? [\"text\"]'
new = 'input: (id === \"kimi-k2.5:cloud\" || (Array.isArray(model.tags) && model.tags.includes(\"vision\"))) ? [\"text\", \"image\"] : Array.isArray(model.tags) ? [\"text\"] : fallback?.input ?? [\"text\"]'

old2 = 'input: [\"text\"],'
new2 = 'input: (modelId === \"kimi-k2.5:cloud\" || modelId === \"qwen3-vl:235b-cloud\" || /qwen.*vl|llava|minicpm-v|moondream/i.test(modelId)) ? [\"text\", \"image\"] : [\"text\"],'

patched = False
if old in content:
    content = content.replace(old, new)
    patched = True
if 'buildOllamaModelDefinition' in content and old2 in content[content.find('buildOllamaModelDefinition'):content.find('buildOllamaModelDefinition')+300]:
    idx = content.find('buildOllamaModelDefinition')
    section = content[idx:idx+300]
    content = content[:idx] + section.replace(old2, new2, 1) + content[idx+300:]
    patched = True

if patched:
    with open('$FILE', 'w') as f:
        f.write(content)
    print('✅ Vision patch applied')
else:
    print('ℹ️ Already patched or pattern changed')
"
