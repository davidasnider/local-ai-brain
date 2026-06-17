---
name: restart-dev
description: Forcefully kills and restarts the local development server on port 8888.
---

# restart-dev

This skill forcefully restarts the local development server running on port 8888. 

## Instructions

If the `run-dev` process gets stuck or you need to cleanly restart it in the background, run the following commands in the repository root:

```bash
# 1. Find and kill the existing uvicorn processes bound to port 8888
lsof -ti:8888 | xargs kill 2>/dev/null || true

# 2. Start the development server again
set -a && source .env && set +a && PYTHONPATH=src uv run uvicorn local_ai_brain.main:app --host 0.0.0.0 --port 8888 --reload > /tmp/localbrain-dev.log 2>&1 &
```
