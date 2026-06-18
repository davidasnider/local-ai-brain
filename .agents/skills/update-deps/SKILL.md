---
name: update-deps
description: Updates development dependencies (llama-cpp-python) and checks for Hugging Face model updates.
---

1. Upgrades `llama-cpp-python` to the latest available version via `uv`.
2. Runs `uv sync` to update the lockfile and install dependencies.
3. Checks Hugging Face for new commits on the models in use.

```bash
set -euo pipefail

# Source environment variables from .env (if present)
if [ -f .env ]; then
  set -a && source .env && set +a
fi

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
model_name = sys.argv[1]
for m in cfg.get('models', []):
    if m.get('name') == model_name:
        repo_id = m.get('hf_model_repo_id')
        if repo_id:
            print(f'https://huggingface.co/{repo_id}')
            sys.exit(0)
sys.exit(1)
" "$model_name"
}

check_model() {
  local name=$1
  local url=$2
  echo -n "Checking $name... "
  # Skip git check for local filesystem paths
  if [ -d "$url" ] || [ -f "$url" ]; then
    echo "Local path — skipping remote check"
    return
  fi
  # Prepend https://huggingface.co/ if it's a simple repo identifier
  if [[ "$url" != http://* ]] && [[ "$url" != https://* ]] && [[ "$url" != /* ]] && [[ "$url" != .* ]]; then
    url="https://huggingface.co/$url"
  fi
  if COMMIT=$(git ls-remote "$url" HEAD 2>/dev/null | cut -f1); then
    echo "Latest remote commit: $COMMIT"
  else
    echo "WARNING: Could not reach $url (network issue or rate limit)"
  fi
}

QWEN_27B=$(get_model_url "qwen-27b-4bit" 2>/dev/null || echo "")
if [ -n "$QWEN_27B" ]; then
  check_model "Qwen (active)" "$QWEN_27B"
else
  echo "Warning: qwen-27b-4bit not found in llm_config.yaml -- skipping"
fi

QWEN_35B=$(get_model_url "qwen-35b-4bit" 2>/dev/null || echo "")
if [ -n "$QWEN_35B" ]; then
  check_model "Qwen (fallback)" "$QWEN_35B"
else
  echo "Warning: qwen-35b-4bit not found in llm_config.yaml -- skipping"
fi

WHISPER_URL="${WHISPER_MODEL_PATH:-https://huggingface.co/mlx-community/whisper-large-v3-mlx}"
KOKORO_URL="${KOKORO_HF_REPO:-https://huggingface.co/fastrtc/kokoro-onnx}"
check_model "Whisper" "$WHISPER_URL"
check_model "Kokoro" "$KOKORO_URL"

echo "✅ Update check complete."
```
