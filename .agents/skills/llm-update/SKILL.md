---
name: llm-update
description: Updates llama-cpp-python to the latest version and checks for model updates on Hugging Face.
---

1. Runs `uv lock --upgrade-package llama-cpp-python` to update the lockfile.
2. Runs `uv sync` to install dependencies.
3. Checks Hugging Face for new commits on the models in use.

```bash
# Update llama-cpp-python
echo "🔄 Checking for llama-cpp-python updates..."
uv lock --upgrade-package llama-cpp-python
echo "🔄 Running uv sync (this may take a minute)..."
uv sync
echo "✅ llama-cpp-python update complete."

# Check Models
echo "🔍 Checking for model updates on Hugging Face..."

check_model() {
  local name=$1
  local url=$2
  echo -n "Checking $name... "
  COMMIT=$(git ls-remote $url HEAD | cut -f1)
  echo "Latest remote commit: $COMMIT"
}

check_model "Qwen 35B" "https://huggingface.co/unsloth/Qwen3.6-35B-A3B-MTP-GGUF"
check_model "Qwen 27B" "https://huggingface.co/unsloth/Qwen3.6-27B-MTP-GGUF"
check_model "Whisper" "https://huggingface.co/mlx-community/whisper-large-v3-mlx"
check_model "Kokoro" "https://huggingface.co/fastrtc/kokoro-onnx"

echo "✅ Update check complete."
```
