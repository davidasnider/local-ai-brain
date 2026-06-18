---
name: update-deps
description: Updates development dependencies (llama-cpp-python) and checks for Hugging Face model updates.
---

1. Upgrades `llama-cpp-python` to the latest available version via `uv`.
2. Runs `uv sync` to update the lockfile and install dependencies.
3. Checks Hugging Face for new commits on the models in use.

```bash
set -euo pipefail

# Update llama-cpp-python
echo "🔄 Checking for llama-cpp-python updates..."
uv sync --upgrade-package llama-cpp-python
echo "✅ llama-cpp-python updated (or already at latest)."

# Check Models
echo "🔍 Checking for model updates on Hugging Face..."

get_model_url() {
  local model_name=$1
  uv run python -c "
import yaml, sys
with open('llm_config.yaml') as f:
    cfg = yaml.safe_load(f)
for m in cfg.get('models', []):
    if m.get('name') == '$model_name':
        print(f'https://huggingface.co/{m[\"hf_model_repo_id\"]}')
        sys.exit(0)
sys.exit(1)
"
}

check_model() {
  local name=$1
  local url=$2
  echo -n "Checking $name... "
  if COMMIT=$(git ls-remote "$url" HEAD 2>/dev/null | cut -f1); then
    echo "Latest remote commit: $COMMIT"
  else
    echo "WARNING: Could not reach $url (network issue or rate limit)"
  fi
}

check_model "Qwen (active)" "$(get_model_url qwen-27b-4bit)"
check_model "Qwen (fallback)" "$(get_model_url qwen-35b-4bit)"
check_model "Whisper" "https://huggingface.co/mlx-community/whisper-large-v3-mlx"
check_model "Kokoro" "https://huggingface.co/fastrtc/kokoro-onnx"

echo "✅ Update check complete."
```
