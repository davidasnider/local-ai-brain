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

# NOTE: The Hugging Face repository URLs below must be kept in sync with the
# model configurations and paths defined in llm_config.yaml.
check_model "Qwen (active)" "https://huggingface.co/unsloth/Qwen3.6-27B-MTP-GGUF"
check_model "Qwen (fallback)" "https://huggingface.co/unsloth/Qwen3.6-35B-A3B-MTP-GGUF"
check_model "Whisper" "https://huggingface.co/mlx-community/whisper-large-v3-mlx"
check_model "Kokoro" "https://huggingface.co/fastrtc/kokoro-onnx"

echo "✅ Update check complete."
```
