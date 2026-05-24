#!/usr/bin/env bash

set -e

AGX_RELAX_CDM_CTXSTORE_TIMEOUT=1 mlx_lm.server \
  --model mlx-community/Qwen3.6-35B-A3B-4bit \
  --chat-template-args '{"enable_thinking": true, "preserve_thinking": true}' \
  --prompt-cache-bytes 10737418240 \
  --prefill-step-size 1024 \
  --port 8000 \
  --reasoning-parser qwen3
