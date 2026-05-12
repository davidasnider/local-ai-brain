"""Wrapper for vllm_mlx.server with optimized configuration for local execution.

This module provides a way to run the vllm_mlx server with appropriate logging
configuration for the Local AI Brain system.
"""

from loguru import logger

from local_ai_brain.logging import configure_logging


def main():
    """Main entry point for the vLLM server."""
    from local_ai_brain.config import settings

    configure_logging(testing=settings.TESTING)

    try:
        import vllm_mlx.server
    except ImportError as e:
        logger.error(f"Failed to import vllm-mlx: {e}")
        raise SystemExit(1) from e

    # Run the original server main function with existing CLI arguments
    vllm_mlx.server.main()


if __name__ == "__main__":
    main()
