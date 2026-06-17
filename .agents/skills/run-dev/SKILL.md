---
name: run-dev
description: Launches the Local AI Brain API in development mode on port 8888 with hot-reload.
---

# run-dev

This skill launches the Local AI Brain API locally in development mode on port 8888.

## Instructions

To start the development server, ensure you are in the repository root and run the following command:

```bash
set -a && source .env && set +a && PYTHONPATH=src uv run uvicorn local_ai_brain.main:app --host 0.0.0.0 --port 8888 --reload > /tmp/localbrain-dev.log 2>&1
```

The application will use the `LOCAL_API_KEY` loaded from your `.env` file.
