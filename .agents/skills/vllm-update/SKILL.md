---
name: vllm-update
description: Updates vllm-mlx to the latest version and checks for model updates on Hugging Face.
---

1. Fetches the latest commit hash for `vllm-mlx` from GitHub.
2. Updates `pyproject.toml` with the new hash.
3. Runs `uv sync` to update the lockfile and install dependencies.
4. Checks Hugging Face for new commits on the models in use.

```bash
# Update vllm-mlx
echo "🔄 Checking for vllm-mlx updates..."
REPO_URL="https://github.com/waybarrios/vllm-mlx.git"
CURRENT_HASH=$(grep -oE 'rev = "[a-f0-9]+"' pyproject.toml | cut -d'"' -f2)
LATEST_HASH=$(git ls-remote $REPO_URL HEAD | cut -f1)

if [ "$CURRENT_HASH" != "$LATEST_HASH" ]; then
  echo "⬆️ New version found: $LATEST_HASH"
  # Use sed to replace the hash (macOS syntax)
  sed -i '' "s/rev = \"$CURRENT_HASH\"/rev = \"$LATEST_HASH\"/" pyproject.toml
  echo "✅ Updated pyproject.toml"
  echo "🔄 Running uv sync..."
  uv sync
else
  echo "✅ vllm-mlx is already at the latest version ($CURRENT_HASH)."
fi

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
