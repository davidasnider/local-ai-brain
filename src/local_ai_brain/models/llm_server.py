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


def _quant_str(value) -> str:
    """Map integer cache quantization values to string equivalents, passing others as-is."""
    mapping = {
        8: "q8_0",
        4: "q4_0",
        16: "f16",
    }
    if value in mapping:
        return mapping[value]
    try:
        val_int = int(value)
        if val_int in mapping:
            return mapping[val_int]
    except (ValueError, TypeError):
        pass
    return str(value)


def build_command(config: dict, host: str, port: str) -> list[str]:
    """Build the CLI arguments for llama-server."""
    from local_ai_brain.config import settings

    cmd = ["llama-server"]

    # Model settings
    default_repo = ""
    default_file = settings.QWEN_MODEL_PATH
    if ":" in settings.QWEN_MODEL_PATH:
        default_repo, default_file = settings.QWEN_MODEL_PATH.split(":", 1)

    model_file_val = config.get("model")
    model_file = str(model_file_val if model_file_val is not None else default_file)

    has_fs_characteristics = (
        "/" in model_file
        or any(model_file.endswith(ext) for ext in (".gguf", ".bin", ".pt", ".safetensors", ".mlx"))
        or model_file.startswith("/")
        or model_file.startswith("./")
        or model_file.startswith("../")
        or model_file.startswith("~")
    )

    is_local_path = model_file != "" and (
        model_file.startswith("/")
        or model_file.startswith("./")
        or model_file.startswith("../")
        or model_file.startswith("~")
        or ("/" in model_file and ":" not in model_file and Path(model_file).exists())
        or (has_fs_characteristics and Path(model_file).exists())
        or has_fs_characteristics
    )

    hf_repo_val = config.get("hf_model_repo_id")
    if hf_repo_val is not None:
        hf_repo = str(hf_repo_val)
    else:
        # If not provided, only default to default_repo if model_file is NOT a local path
        if is_local_path:
            hf_repo = ""
        else:
            hf_repo = default_repo

    if model_file.startswith("~"):
        model_file = os.path.expanduser(model_file)

    # Check if we should use the -hf flag or local model path
    if hf_repo:
        model_id = f"{hf_repo}:{model_file}"
        cmd.extend(["-hf", model_id])
        cmd.extend(["--alias", model_id])
    else:
        cmd.extend(["--model", model_file])
        cmd.extend(["--alias", model_file])

    # Performance tunables
    cmd.extend(
        ["-ngl", str(config.get("n_gpu_layers") if config.get("n_gpu_layers") is not None else 99)]
    )
    cmd.extend(
        ["--ctx-size", str(config.get("n_ctx") if config.get("n_ctx") is not None else 98304)]
    )

    if config.get("flash_attn", True):
        cmd.extend(["-fa", "on"])

    cmd.extend(
        ["--batch-size", str(config.get("n_batch") if config.get("n_batch") is not None else 2048)]
    )
    cmd.extend(
        [
            "--ubatch-size",
            str(config.get("n_ubatch") if config.get("n_ubatch") is not None else 2048),
        ]
    )

    # Slots and Speculative Decoding (sourced from config or defaults)
    cmd.extend(
        ["-np", str(config.get("n_parallel") if config.get("n_parallel") is not None else 1)]
    )
    if config.get("spec_type") is not None:
        cmd.extend(["--spec-type", str(config.get("spec_type"))])
    if config.get("spec_draft_n_max") is not None:
        cmd.extend(["--spec-draft-n-max", str(config.get("spec_draft_n_max"))])
    if config.get("spec_draft_p_min") is not None:
        cmd.extend(["--spec-draft-p-min", str(config.get("spec_draft_p_min"))])

    # Cache quantization
    type_k = config.get("type_k")
    if type_k is not None:
        cmd.extend(["--cache-type-k", _quant_str(type_k)])

    type_v = config.get("type_v")
    if type_v is not None:
        cmd.extend(["--cache-type-v", _quant_str(type_v)])

    cmd.extend(["--host", host])
    cmd.extend(["--port", port])

    # API Key injection
    api_key = (
        os.environ.get("OPENAI_API_KEY")
        or os.environ.get("LOCAL_API_KEY")
        or settings.LOCAL_API_KEY
    )
    if api_key:
        os.environ["LLAMA_API_KEY"] = api_key

    return cmd


def main():
    """Main entry point for the llama-server wrapper."""
    from local_ai_brain.config import settings

    configure_logging(testing=settings.TESTING)

    # 1. Parse YAML config if it exists
    from local_ai_brain.config import get_config_path

    config_path = get_config_path(__file__)
    config = {}
    if config_path.exists():
        try:
            with open(config_path, "r") as f:
                loaded = yaml.safe_load(f)
                if isinstance(loaded, dict) and "active_model" in loaded and "models" in loaded:
                    active = loaded["active_model"]
                    for m in loaded["models"]:
                        if m.get("name") == active:
                            config = m
                            break
                    if not config and len(loaded["models"]) > 0:
                        config = loaded["models"][0]
                elif isinstance(loaded, dict) and "models" in loaded and len(loaded["models"]) > 0:
                    config = loaded["models"][0]
                elif isinstance(loaded, dict):
                    config = loaded
        except Exception as e:
            logger.error(f"Failed to parse {config_path}: {e}")
            sys.exit(1)

    # 2. Build CLI arguments for llama-server
    # Handle Network & Security (prioritizing CLI args passed to this wrapper)
    # We look for --host and --port in sys.argv first
    host = "127.0.0.1"
    port = "8001"

    for i, arg in enumerate(sys.argv):
        if arg == "--host" and i + 1 < len(sys.argv):
            host = sys.argv[i + 1]
        elif arg == "--port" and i + 1 < len(sys.argv):
            port = sys.argv[i + 1]

    cmd = build_command(config, host, port)

    # 3. Launch the binary
    logger.info(f"Launching engine: {' '.join(cmd)}")
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
