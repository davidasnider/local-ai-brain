---
name: vllm-update
description: Updates llama-cpp-python to the latest version and checks for Hugging Face model updates.
---

1. Upgrades `llama-cpp-python` to the latest available version via `uv`.
2. Runs `uv sync` to update the lockfile and install dependencies.
3. Checks Hugging Face for new commits on the models in use.

```bash
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
  COMMIT=$(git ls-remote $url HEAD | cut -f1)
  echo "Latest remote commit: $COMMIT"
}

check_model "Qwen" "https://huggingface.co/mlx-community/Qwen3.6-35B-A3B-8bit"
check_model "Whisper" "https://huggingface.co/mlx-community/whisper-large-v3-mlx"
check_model "Kokoro" "https://huggingface.co/fastrtc/kokoro-onnx"

echo "✅ Update check complete."
```
