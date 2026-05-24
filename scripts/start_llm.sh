#!/usr/bin/env bash

# This script launches the optimized llama-cpp-python server standalone on port 8000.
# It uses the defaults defined in src/local_ai_brain/models/llm_server.py
# which can be overridden via llm_config.yaml.

set -e

uv run python -m local_ai_brain.models.llm_server --port 8000
