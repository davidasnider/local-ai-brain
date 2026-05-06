from unittest.mock import MagicMock, patch


def test_patched_init_logic():
    """Verify that patched_init correctly handles prefill_step_size defaulting."""
    # We test the patched_init logic directly.
    # We need to import it here to avoid issues with our mocks.
    from local_ai_brain.models.llm_server import apply_patches

    # Use a dummy class to mock SimpleEngine
    class DummyEngine:
        def __init__(self, *args, **kwargs):
            self.init_args = args
            self.init_kwargs = kwargs

    # Mock SimpleEngine in the module where apply_patches imports it
    with patch("vllm_mlx.engine.simple.SimpleEngine", DummyEngine, create=True):
        apply_patches()
        from vllm_mlx.engine.simple import SimpleEngine

        # Case 1: No prefill_step_size provided -> should set to 512
        instance = SimpleEngine()
        assert instance.init_kwargs["prefill_step_size"] == 512

        # Case 2: 2048 explicitly provided -> should be preserved (addressing PR comment)
        instance = SimpleEngine(prefill_step_size=2048)
        assert instance.init_kwargs["prefill_step_size"] == 2048

        # Case 3: Custom value provided (e.g. 1024) -> should be preserved
        instance = SimpleEngine(prefill_step_size=1024)
        assert instance.init_kwargs["prefill_step_size"] == 1024


def test_monkeypatch_idempotency():
    """Verify that apply_patches can be called multiple times without issues."""
    from local_ai_brain.models.llm_server import apply_patches

    # Mock SimpleEngine
    mock_engine = MagicMock()
    with patch("vllm_mlx.engine.simple.SimpleEngine", mock_engine, create=True):
        apply_patches()
        first_init = mock_engine.__init__
        apply_patches()
        assert mock_engine.__init__ == first_init
