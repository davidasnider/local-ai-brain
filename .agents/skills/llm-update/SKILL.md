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
if ! uv lock --upgrade-package llama-cpp-python; then
  echo "❌ Failed to update llama-cpp-python in lockfile."
  exit 1
fi
echo "🔄 Running uv sync (this may take a minute)..."
if ! uv sync; then
  echo "❌ uv sync failed."
  exit 1
fi
echo "✅ llama-cpp-python update complete."

# Check Models
echo "🔍 Checking for model updates on Hugging Face..."

check_model() {
  local name=$1
  local repo_id=$2
  echo -n "Checking $name ($repo_id)... "
  
  local remote_commit
  remote_commit=$(git ls-remote "https://huggingface.co/$repo_id" HEAD | cut -f1)
  if [ -z "$remote_commit" ]; then
    echo "⚠️ Failed to fetch remote commit."
    return
  fi
  
  local normalized_repo="${repo_id/\//--}"
  local cache_dir="$HOME/.cache/huggingface/hub"
  if [ -n "$HF_HUB_CACHE" ]; then
    cache_dir="$HF_HUB_CACHE"
  elif [ -n "$HF_HOME" ]; then
    cache_dir="$HF_HOME/hub"
  fi
  local refs_dir="${cache_dir}/models--${normalized_repo}/refs"
  local local_ref_file=""
  if [ -f "${refs_dir}/main" ]; then
    local_ref_file="${refs_dir}/main"
  elif [ -d "$refs_dir" ]; then
    local_ref_file=$(find "$refs_dir" -type f | head -n 1)
  fi

  if [ -n "$local_ref_file" ] && [ -f "$local_ref_file" ]; then
    local local_commit
    local_commit=$(cat "$local_ref_file")
    if [ "$local_commit" = "$remote_commit" ]; then
      echo "Up to date (Commit: ${local_commit:0:7})"
    else
      echo "⚠️ UPDATE AVAILABLE! (Local: ${local_commit:0:7} -> Remote: ${remote_commit:0:7})"
    fi
  else
    echo "No local cached commit found (Latest remote: ${remote_commit:0:7})"
  fi
}

check_model "Qwen 35B" "unsloth/Qwen3.6-35B-A3B-MTP-GGUF"
check_model "Qwen 27B" "unsloth/Qwen3.6-27B-MTP-GGUF"
check_model "Whisper" "mlx-community/whisper-large-v3-mlx"
check_model "Kokoro" "fastrtc/kokoro-onnx"

echo "✅ Update check complete."
```
