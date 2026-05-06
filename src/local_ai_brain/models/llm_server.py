"""Wrapper for vllm_mlx.server that patches engine settings to prevent GPU timeouts.

This module provides a way to run the vllm_mlx server with a smaller default
prefill_step_size, which prevents the macOS Metal watchdog from terminating
processes during large prefill operations on Apple Silicon.
"""

from loguru import logger

from local_ai_brain.config import settings
from local_ai_brain.logging import configure_logging

_PATCH_APPLIED = False


def apply_patches():
    """Applies monkeypatches to vllm_mlx to improve stability on Apple Silicon.

    This function is idempotent.
    """
    global _PATCH_APPLIED
    if _PATCH_APPLIED:
        return

    try:
        from vllm_mlx.engine.simple import SimpleEngine
    except ImportError:
        logger.warning("vllm_mlx not found; skipping monkeypatches.")
        return

    original_init = SimpleEngine.__init__

    def patched_init(self, *args, **kwargs):
        """Patched __init__ for SimpleEngine that overrides prefill_step_size.

        Args:
            *args: Variable length argument list passed to original __init__.
            **kwargs: Arbitrary keyword arguments passed to original __init__.
        """
        # If not explicitly provided, default to 512 instead of 2048.
        # This chunks the prefill work into smaller pieces that fit within
        # the macOS 5-second Metal watchdog timer.
        if "prefill_step_size" not in kwargs:
            kwargs["prefill_step_size"] = 512

        original_init(self, *args, **kwargs)

    # Apply the patch
    SimpleEngine.__init__ = patched_init
    _PATCH_APPLIED = True
    logger.info("Patched vllm_mlx.engine.simple.SimpleEngine with prefill_step_size=512")


def main():
    """Main entry point for the patched vLLM server."""
    configure_logging(testing=settings.TESTING)
    apply_patches()

    try:
        import vllm_mlx.server
    except ImportError as e:
        logger.error(f"Failed to import vllm-mlx: {e}")
        raise SystemExit(1) from e

    # Run the original server main function with existing CLI arguments
    vllm_mlx.server.main()


if __name__ == "__main__":
    main()
