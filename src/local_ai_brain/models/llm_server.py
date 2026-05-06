import sys

from loguru import logger

# Import vllm_mlx components for monkeypatching
try:
    import vllm_mlx.server
    from vllm_mlx.engine.simple import SimpleEngine
except ImportError as e:
    logger.error(f"Failed to import vllm-mlx: {e}")
    sys.exit(1)

# Monkeypatch SimpleEngine to use a smaller prefill_step_size by default.
# This prevents Metal GPU timeouts on large models like Qwen3.6-35B.
original_init = SimpleEngine.__init__


def patched_init(self, *args, **kwargs):
    # If not explicitly provided, default to 512 instead of 2048.
    # This chunks the prefill work into smaller pieces that fit within
    # the macOS 5-second Metal watchdog timer.
    if "prefill_step_size" not in kwargs or kwargs["prefill_step_size"] == 2048:
        kwargs["prefill_step_size"] = 512

    original_init(self, *args, **kwargs)


# Apply the patch
SimpleEngine.__init__ = patched_init
logger.info("Patched vllm_mlx.engine.simple.SimpleEngine with prefill_step_size=512")


def main():
    # Run the original server main function with existing CLI arguments
    vllm_mlx.server.main()


if __name__ == "__main__":
    main()
