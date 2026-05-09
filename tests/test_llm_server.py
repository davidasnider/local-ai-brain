import os
from unittest.mock import MagicMock, patch

import pytest

# Set dummy env vars for module-level settings imports in some modules
os.environ.setdefault("LOCAL_API_KEY", "test-key")
os.environ.setdefault("TESTING", "1")


@pytest.fixture(autouse=True)
def reset_patches():
    """Reset the monkeypatch state before each test to ensure isolation."""
    import local_ai_brain.models.llm_server

    local_ai_brain.models.llm_server._PATCH_APPLIED = False
    yield


@pytest.fixture
def mock_vllm_mlx():
    """Stub out vllm_mlx in sys.modules to keep tests hermetic and independent of vLLM."""
    mock_simple = MagicMock()
    mock_engine = MagicMock()
    mock_server = MagicMock()

    # We use a real class for SimpleEngine to properly test attribute assignment
    class SimpleEngine:
        def __init__(self, prefill_step_size=None, max_num_seqs=None, *args, **kwargs):
            self.init_args = args
            self.init_kwargs = {
                "prefill_step_size": prefill_step_size,
                "max_num_seqs": max_num_seqs,
                **kwargs,
            }

    mock_engine.SimpleEngine = SimpleEngine

    with patch.dict(
        "sys.modules",
        {
            "vllm_mlx": mock_simple,
            "vllm_mlx.engine": mock_engine,
            "vllm_mlx.engine.simple": mock_engine,
            "vllm_mlx.server": mock_server,
        },
    ):
        yield mock_engine, mock_server


def test_patched_init_logic(mock_vllm_mlx):
    """Verify that patched_init correctly handles default overrides."""
    from local_ai_brain.models.llm_server import apply_patches

    mock_engine, _ = mock_vllm_mlx
    apply_patches()

    # Case 1: No arguments provided -> should set defaults
    instance = mock_engine.SimpleEngine()
    assert instance.init_kwargs["prefill_step_size"] == 128
    assert instance.init_kwargs["max_num_seqs"] == 1

    # Case 2: Values explicitly provided via kwargs -> should be preserved
    instance = mock_engine.SimpleEngine(prefill_step_size=2048, max_num_seqs=4)
    assert instance.init_kwargs["prefill_step_size"] == 2048
    assert instance.init_kwargs["max_num_seqs"] == 4

    # Case 3: Values explicitly provided via positional args -> should be preserved
    # Note: SimpleEngine(2048, 4) passes 2048 as prefill_step_size and 4 as max_num_seqs
    instance = mock_engine.SimpleEngine(2048, 4)
    assert instance.init_kwargs["prefill_step_size"] == 2048
    assert instance.init_kwargs["max_num_seqs"] == 4


def test_monkeypatch_idempotency(mock_vllm_mlx):
    """Verify that apply_patches can be called multiple times without double-patching."""
    from local_ai_brain.models.llm_server import apply_patches

    mock_engine, _ = mock_vllm_mlx

    apply_patches()
    first_init = mock_engine.SimpleEngine.__init__

    apply_patches()
    assert mock_engine.SimpleEngine.__init__ == first_init


def test_main_failure_exits_nonzero(mock_vllm_mlx):
    """Verify that main() exits with status 1 if vllm-mlx is not importable."""
    from local_ai_brain.models.llm_server import main

    # Simulate missing vllm_mlx.server only
    with patch.dict("sys.modules", {"vllm_mlx.server": None}):
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 1
