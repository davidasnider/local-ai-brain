"""Wrapper for vllm_mlx.server that patches engine settings to prevent GPU timeouts.

This module provides a way to run the vllm_mlx server with a very small default
prefill_step_size (128) and restricted max_num_seqs (1), which prevents the macOS
Metal watchdog from terminating processes during large or concurrent prefill
operations on Apple Silicon.
"""

from loguru import logger

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

    import inspect

    original_init = SimpleEngine.__init__
    sig = inspect.signature(original_init)

    def patched_init(self, *args, **kwargs):
        """Patched __init__ for SimpleEngine that overrides engine parameters.

        Args:
            *args: Variable length argument list passed to original __init__.
            **kwargs: Arbitrary keyword arguments passed to original __init__.
        """
        # Bind the provided arguments to the original signature to see what's set
        bound = sig.bind_partial(self, *args, **kwargs)

<<<<<<< HEAD
        # If not explicitly provided, default to 128 instead of 2048.
        # This chunks the prefill work into smaller pieces that fit within
        # the macOS 5-second Metal watchdog timer.
        # We use 128 (very conservative) to prevent timeouts on large models.
        applied = []
        if "prefill_step_size" in sig.parameters and "prefill_step_size" not in bound.arguments:
            kwargs["prefill_step_size"] = 128
            applied.append("prefill_step_size=128")
=======
        # If not explicitly provided, default to 512 instead of 2048.
        # This chunks the prefill work into smaller pieces that fit within
        # the macOS 5-second Metal watchdog timer.
        if "prefill_step_size" in sig.parameters and "prefill_step_size" not in bound.arguments:
            kwargs["prefill_step_size"] = 512
>>>>>>> 214b0a0 (fix: address PR feedback on semaphore scope and engine patching)

        # Limit concurrency to prevent multiple large prefills from triggering
        # the GPU watchdog.
        if "max_num_seqs" in sig.parameters and "max_num_seqs" not in bound.arguments:
            kwargs["max_num_seqs"] = 1
            applied.append("max_num_seqs=1")

        if applied:
            logger.info(f"Applying engine stability overrides: {', '.join(applied)}")

        original_init(self, *args, **kwargs)

    # Apply the patch
    SimpleEngine.__init__ = patched_init
    _PATCH_APPLIED = True

    overrides = []
    if "prefill_step_size" in sig.parameters:
<<<<<<< HEAD
        overrides.append("prefill_step_size=128")
=======
        overrides.append("prefill_step_size=512")
>>>>>>> 214b0a0 (fix: address PR feedback on semaphore scope and engine patching)
    if "max_num_seqs" in sig.parameters:
        overrides.append("max_num_seqs=1")

    if overrides:
        logger.info(f"Patched vllm_mlx.engine.simple.SimpleEngine with {', '.join(overrides)}")
    else:
        logger.info("No supported stability overrides found for SimpleEngine signature.")


def main():
    """Main entry point for the patched vLLM server."""
    from local_ai_brain.config import settings

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
