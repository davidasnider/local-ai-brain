---
name: update-deps
description: Updates development dependencies (llama-cpp-python) and checks for Hugging Face model updates.
---

1. Upgrades `llama-cpp-python` to the latest available version via `uv`.
2. Runs `uv sync` to update the lockfile and install dependencies.
3. Checks Hugging Face for new commits on the models in use.

```bash
#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=""
_dir="$(pwd)"
while [ "$_dir" != "/" ]; do
  if [ -f "$_dir/pyproject.toml" ]; then
    PROJECT_ROOT="$_dir"
    break
  fi
  _dir="$(dirname "$_dir")"
done
if [ -z "$PROJECT_ROOT" ]; then echo "ERROR: Could not find project root" >&2; exit 1; fi
cd "$PROJECT_ROOT"

# Source environment variables from .env (if present)
if [ -f .env ]; then
  set -a && source .env && set +a
fi

export PYTHONPATH=src

# Update llama-cpp-python
echo "🔄 Checking for llama-cpp-python updates..."
uv sync --upgrade-package llama-cpp-python
echo "✅ llama-cpp-python updated (or already at latest)."

# Check Models
echo "🔍 Checking for model updates on Hugging Face..."

check_model() {
  local name=$1
  local url=$2
  if [ -z "$url" ]; then
    return
  fi
  echo -n "Checking $name... "
  # Skip git check for local filesystem paths
  url="${url/#\~/$HOME}"
  if [ -d "$url" ] || [ -f "$url" ]; then
    echo "Local path — skipping remote check"
    return
  fi
  # If it looks like a local filesystem path (starts with / or ., or contains a slash
  # where the first component is an existing directory), but does not exist yet, skip git check.
  # Note: Local relative paths should start with ./ or ../ to be unambiguously recognized
  # if their parent directories do not exist yet.
  if [[ "$url" == /* ]] || [[ "$url" == .* ]] || { [[ "$url" == */* ]] && [ -d "${url%%/*}" ]; }; then
    echo "Local path does not exist yet -- skipping remote check"
    return
  fi

  # Prepend https://huggingface.co/ if it's a simple repo identifier
  if [[ "$url" != http://* ]] && [[ "$url" != https://* ]] && [[ "$url" != /* ]] && [[ "$url" != .* ]]; then
    url="https://huggingface.co/$url"
  fi
  if COMMIT=$(git ls-remote -- "$url" HEAD 2>/dev/null | cut -f1); then
    echo "Latest remote commit: $COMMIT"
  else
    echo "WARNING: Could not reach $url (network issue or rate limit)"
  fi
}

echo "Checking models from llm_config.yaml..."
uv run python -c "
import sys
import yaml
from pathlib import Path
cfg_path = Path.cwd()
for parent in [cfg_path] + list(cfg_path.parents):
    if (parent / 'pyproject.toml').exists() or (parent / 'llm_config.yaml').exists():
        cfg_path = parent / 'llm_config.yaml'
        break
else:
    cfg_path = cfg_path / 'llm_config.yaml'
if cfg_path.exists():
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f) or {}
else:
    print(f'WARNING: llm_config.yaml not found, skipping model checks', file=sys.stderr)
    cfg = {}
active = cfg.get('active_model', '')
models = cfg.get('models') or []
for m in models:
    name = m.get('name', 'unknown')
    label = name
    if name == active:
        label = name + ' (active)'
    repo_id = m.get('hf_model_repo_id')
    if repo_id:
        url = 'https://huggingface.co/' + repo_id
        print(f'MODEL_CHECK:{label}|{url}')
    else:
        print(f'Skipping {name}: no hf_model_repo_id')
" | while IFS='|' read -r label url; do
  if [ "$label" = "${label#MODEL_CHECK:}" ]; then
    echo "$label"
  else
    label="${label#MODEL_CHECK:}"
    check_model "$label" "$url"
  fi
done

WHISPER_URL="${WHISPER_MODEL_PATH:-https://huggingface.co/mlx-community/whisper-large-v3-mlx}"
KOKORO_URL="${KOKORO_HF_REPO:-https://huggingface.co/fastrtc/kokoro-onnx}"
check_model "Whisper" "$WHISPER_URL"
check_model "Kokoro" "$KOKORO_URL"

echo "✅ Update check complete."
```
