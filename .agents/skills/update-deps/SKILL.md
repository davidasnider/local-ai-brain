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
# Use Python to parse .env safely — handles inline comments and
# whitespace around '=' that bash sourcing would mangle.
if [ -f .env ]; then
  eval "$(python3 << 'PYEOF'
import shlex
import re
with open(".env") as _f:
    for _line in _f:
        _line = _line.strip()
        if not _line or _line.startswith("#"):
            continue
        if "=" not in _line:
            continue
        _key, _, _val = _line.partition("=")
        _key = _key.strip()
        _val = _val.strip()
        if len(_val) >= 2 and _val[0] == _val[-1] and _val[0] in ('"', "'"):
            _val = _val[1:-1]
        elif "#" in _val:
            _hash_idx = _val.index("#")
            if _hash_idx == 0 or _val[_hash_idx - 1] in (" ", "\t"):
                _val = _val[:_hash_idx].rstrip()
        if _key and re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", _key):
            print(f"export {_key}={shlex.quote(_val)}")
PYEOF
)"
fi

export PYTHONPATH=src

# Update llama-cpp-python
echo "🔄 Checking for llama-cpp-python updates..."
uv sync --upgrade-package llama-cpp-python
echo "✅ llama-cpp-python updated (or already at latest)."

# Check Models
echo "🔍 Checking for model updates on Hugging Face..."

check_model() {
  local name="$1"
  local url="$2"
  if [ -z "$url" ]; then
    return
  fi
  echo -n "Checking $name... "
  # Skip git check for local filesystem paths
  url="${url/#\~/$HOME}"

  if [[ "$url" == http://* ]] || [[ "$url" == https://* ]]; then
    # Bypass all local-path heuristics for HTTP/HTTPS URLs and go directly to git ls-remote check
    :
  else
    if [ -d "$url" ] || [ -f "$url" ]; then
      echo "Local path ($name) — skipping remote check"
      return
    fi

    # Warn about ambiguous single-slash paths, but don't early-return — the URL
    # may still be a valid HF repo ID (org/repo format). Let the subsequent
    # checks (multi-slash, extension, exists) handle it, and if none match
    # the URL gets https://huggingface.co/ prepended below.
    if [[ "$url" == *"/"* ]] && [[ "$url" != "./"* ]] && [[ "$url" != "../"* ]] && [[ "$url" != "/"* ]] && [ ! -e "$url" ]; then
        local _slash_count="${url//[^\/]/}"
        if [ ${#_slash_count} -eq 1 ]; then
            echo "Warning: \"$url\" looks like a local path with one slash but lacks ./ or ../ prefix. If this is a HF repo ID it will be checked; if it's a local path, prefix with ./ or ../ to silence this warning." >&2
        fi
    fi

    # First, detect local relative paths that don't exist on disk yet but look like filesystem paths.
    # HuggingFace repo IDs are always org/repo (exactly one "/"), so multi-component paths
    # (more than one "/") are unambiguously local filesystem paths.
    local _slash_count="${url//[^\/]/}"
    if [ ${#_slash_count} -gt 1 ]; then
      echo "Local path ($name, multi-component) — skipping remote check"
      return
    fi

    # Check if the complete $url exists as a local file or directory on disk.
    # Using -e (exists) is more precise than checking only the parent directory,
    # which could match an HF org name (e.g., mlx-community) if a developer
    # happens to create a local folder with that name, incorrectly skipping
    # the remote update check for that HF repository.
    if [ -e "$url" ] 2>/dev/null; then
      echo "Local path ($url exists) — skipping remote check"
      return
    fi

    # Detect local file paths by extension — a path like "models/whisper.gguf"
    # has exactly one "/" and starts with neither "/" nor ".", so it would
    # bypass the slash-count and absolute-path checks and incorrectly get
    # https://huggingface.co/ prepended.  Explicitly match known model file
    # extensions to treat them as local paths (finding #2).
    case "$url" in
      *.gguf|*.bin|*.onnx|*.pt|*.safetensors|*.pth|*.ckpt)
        echo "Local path ($name, detected by extension) — skipping remote check"
        return
        ;;
    esac

    if [[ "$url" != /* ]] && [[ "$url" != .* ]]; then
      url="https://huggingface.co/$url"
    else
      # If it looks like a local filesystem path (starts with / or .), but does not exist yet, skip git check.
      # Note: Local relative paths should start with ./ or ../ to be unambiguously recognized
      # if their parent directories do not exist yet.
      echo "Local path ($name) does not exist yet -- skipping remote check"
      return
    fi
  fi
  local COMMIT
  if COMMIT=$(GIT_TERMINAL_PROMPT=0 git ls-remote -- "$url" HEAD 2>/dev/null | cut -f1); then
    echo "Latest remote commit: $COMMIT"
  else
    echo "WARNING: Could not check $url for remote updates — network issue, rate limit, or invalid repository"
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
        try:
            cfg = yaml.safe_load(f) or {}
            if not isinstance(cfg, dict): cfg = {}
        except yaml.YAMLError as e:
            print(f'WARNING: Could not parse llm_config.yaml: {e}', file=sys.stderr)
            cfg = {}
else:
    print(f'WARNING: llm_config.yaml not found, skipping model checks', file=sys.stderr)
    cfg = {}
active = cfg.get('active_model', '')
models = cfg.get('models') or []
if not isinstance(models, list):
    models = []
for m in models:
    if not isinstance(m, dict):
        continue
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
