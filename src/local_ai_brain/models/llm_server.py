"""Wrapper for vllm_mlx.server that configures logging for the Local AI Brain system.

This module provides a way to run the vllm_mlx server with appropriate logging
configuration.
"""

import importlib
import os
import sys

from loguru import logger

from local_ai_brain.logging import configure_logging


def main():
    """Main entry point for the vLLM server."""
    from local_ai_brain.config import settings

    configure_logging(testing=settings.TESTING)

    # Inject API key from environment if present and not already in args
    # to avoid leaking it in process listings.
    if "VLLM_API_KEY" in os.environ and "--api-key" not in sys.argv:
        sys.argv.extend(["--api-key", os.environ["VLLM_API_KEY"]])

    try:
        vllm_server = importlib.import_module("vllm_mlx.server")
    except ImportError as e:
        logger.error(f"Failed to import vllm-mlx: {e}")
        raise SystemExit(1) from e

    # Run the original server main function with existing CLI arguments
    vllm_server.main()


if __name__ == "__main__":
    main()
