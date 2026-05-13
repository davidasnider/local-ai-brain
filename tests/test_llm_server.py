import os
from unittest.mock import patch

import pytest

# Set dummy env vars for module-level settings imports in some modules
os.environ.setdefault("LOCAL_API_KEY", "test-key")
os.environ.setdefault("TESTING", "1")


def test_main_failure_exits_nonzero():
    """Verify that main() exits with status 1 if vllm-mlx is not importable."""
    import importlib

    from local_ai_brain.models.llm_server import main

    real_import_module = importlib.import_module

    def mocked_import_module(name, *args, **kwargs):
        if name == "vllm_mlx.server":
            raise ImportError("Mocked error")
        return real_import_module(name, *args, **kwargs)

    # Simulate missing vllm_mlx.server
    with patch("importlib.import_module", side_effect=mocked_import_module):
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 1


def test_main_runs_server():
    """Verify that main() correctly invokes vllm_mlx.server.main()."""
    import importlib
    from unittest.mock import MagicMock

    from local_ai_brain.models.llm_server import main

    real_import_module = importlib.import_module
    mock_server = MagicMock()

    def mocked_import_module(name, *args, **kwargs):
        if name == "vllm_mlx.server":
            return mock_server
        return real_import_module(name, *args, **kwargs)

    with patch("importlib.import_module", side_effect=mocked_import_module):
        main()
        mock_server.main.assert_called_once()
