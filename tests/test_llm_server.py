import os
from unittest.mock import patch

import pytest

# Set dummy env vars for module-level settings imports in some modules
os.environ.setdefault("LOCAL_API_KEY", "test-key")
os.environ.setdefault("TESTING", "1")


def test_main_failure_exits_nonzero():
    """Verify that main() exits with status 1 if vllm-mlx is not importable."""
    from local_ai_brain.models.llm_server import main

    # Simulate missing vllm_mlx.server
    with patch.dict("sys.modules", {"vllm_mlx.server": None}):
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 1


def test_main_runs_server():
    """Verify that main() correctly invokes vllm_mlx.server.main()."""
    from local_ai_brain.models.llm_server import main

    with patch("vllm_mlx.server.main") as mock_server_main:
        main()
        mock_server_main.assert_called_once()
