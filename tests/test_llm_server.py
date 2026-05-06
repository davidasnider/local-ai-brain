from unittest.mock import MagicMock, patch

import pytest


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
        def __init__(self, *args, **kwargs):
            self.init_args = args
            self.init_kwargs = kwargs

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
    """Verify that patched_init correctly handles prefill_step_size defaulting."""
    from local_ai_brain.models.llm_server import apply_patches

    mock_engine, _ = mock_vllm_mlx
    apply_patches()

    # Case 1: No prefill_step_size provided -> should set to 512
    instance = mock_engine.SimpleEngine()
    assert instance.init_kwargs["prefill_step_size"] == 512

    # Case 2: 2048 explicitly provided -> should be preserved (addressing PR comment)
    instance = mock_engine.SimpleEngine(prefill_step_size=2048)
    assert instance.init_kwargs["prefill_step_size"] == 2048

    # Case 3: Custom value provided (e.g. 1024) -> should be preserved
    instance = mock_engine.SimpleEngine(prefill_step_size=1024)
    assert instance.init_kwargs["prefill_step_size"] == 1024


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
