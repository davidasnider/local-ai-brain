"""Wrapper for the llama-server binary that integrates with the Local AI Brain system.

This module parses the YAML config and launches the optimized llama-server binary
with settings matched to Apple Silicon, ensuring compatibility with new model
architectures like Qwen 3.6.
"""

import os
import sys
from pathlib import Path

import yaml
from loguru import logger

from local_ai_brain.logging import configure_logging


def build_command(config: dict, host: str, port: str) -> list[str]:
    """Build the CLI arguments for llama-server."""
    cmd = ["llama-server"]

    # Model settings
    hf_repo = config.get("hf_model_repo_id", "unsloth/Qwen3.6-35B-A3B-MTP-GGUF")
    model_file = config.get("model", "UD-Q4_K_M")

    # Check if we should use the -hf flag or local model path
    if hf_repo:
        # Original script used -hf repo:file format
        cmd.extend(["-hf", f"{hf_repo}:{model_file}"])
    else:
        cmd.extend(["--model", model_file])

    # Performance tunables
    cmd.extend(["-ngl", str(config.get("n_gpu_layers", 99))])
    cmd.extend(["--ctx-size", str(config.get("n_ctx", 98304))])

    if config.get("flash_attn", True):
        cmd.extend(["--flash-attn", "on"])

    cmd.extend(["--batch-size", str(config.get("n_batch", 2048))])
    cmd.extend(["--ubatch-size", str(config.get("n_ubatch", 2048))])

    # Slots and Speculative Decoding from original script
    cmd.extend(["-np", "1"])
    cmd.extend(["--spec-draft-n-max", "2"])
    cmd.extend(["--spec-draft-p-min", "0.75"])

    # Cache quantization (mapping 8 -> q8_0 for llama-server)
    type_k = config.get("type_k")
    if type_k == 8 or type_k == "q8_0":
        cmd.extend(["--cache-type-k", "q8_0"])

    type_v = config.get("type_v")
    if type_v == 8 or type_v == "q8_0":
        cmd.extend(["--cache-type-v", "q8_0"])

    cmd.extend(["--host", host])
    cmd.extend(["--port", port])

    # API Key injection
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("LOCAL_API_KEY")
    if api_key:
        cmd.extend(["--api-key", api_key])

    return cmd


def main():
    """Main entry point for the llama-server wrapper."""
    from local_ai_brain.config import settings

    configure_logging(testing=settings.TESTING)

    # 1. Parse YAML config if it exists
    config_path = Path("llm_config.yaml")
    config = {}
    if config_path.exists():
        try:
            with open(config_path, "r") as f:
                loaded = yaml.safe_load(f)
                if loaded and "models" in loaded and len(loaded["models"]) > 0:
                    config = loaded["models"][0]
                elif loaded:
                    config = loaded
        except Exception as e:
            logger.error(f"Failed to parse {config_path}: {e}")
            sys.exit(1)

    # 2. Build CLI arguments for llama-server
    # Handle Network & Security (prioritizing CLI args passed to this wrapper)
    # We look for --host and --port in sys.argv first
    host = "127.0.0.1"
    port = "8000"

    for i, arg in enumerate(sys.argv):
        if arg == "--host" and i + 1 < len(sys.argv):
            host = sys.argv[i + 1]
        elif arg == "--port" and i + 1 < len(sys.argv):
            port = sys.argv[i + 1]

    cmd = build_command(config, host, port)

    # 3. Launch the binary
    # Sanitize command for logging (redact API key)
    log_cmd = []
    skip_next = False
    for i, arg in enumerate(cmd):
        if skip_next:
            skip_next = False
            continue
        if arg == "--api-key":
            log_cmd.extend([arg, "********"])
            skip_next = True
        else:
            log_cmd.append(arg)

    logger.info(f"Launching engine: {' '.join(log_cmd)}")
    try:
        # We use execvp to replace the current process with llama-server
        # so that signals and process management work correctly.
        os.execvp("llama-server", cmd)
    except FileNotFoundError:
        logger.error("Error: 'llama-server' binary not found in PATH.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to launch llama-server: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
