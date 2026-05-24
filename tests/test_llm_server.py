import os
from unittest.mock import mock_open, patch

import pytest

# Set dummy env vars for module-level settings imports in some modules
os.environ.setdefault("LOCAL_API_KEY", "test-key")
os.environ.setdefault("TESTING", "1")


@patch("local_ai_brain.models.llm_server.configure_logging")
@patch("os.environ", {"LOCAL_API_KEY": "test-api-key"})  # pragma: allowlist secret
@patch("os.execvp")
def test_main_success(mock_exec, mock_log):
    """Verify that main() builds the correct command and calls execvp."""
    from local_ai_brain.models.llm_server import main

    yaml_content = """
models:
  - model: "test-model.gguf"
    n_ctx: 2048
    n_gpu_layers: 30
"""
    with patch("builtins.open", mock_open(read_data=yaml_content)):
        with patch("local_ai_brain.models.llm_server.Path.exists", return_value=True):
            # Mock sys.argv to simulate CLI overrides
            with patch("sys.argv", ["llm_server", "--host", "1.2.3.4", "--port", "5555"]):
                main()

                mock_exec.assert_called_once()
                args = mock_exec.call_args[0]
                assert args[0] == "llama-server"
                cmd = args[1]
                assert "-hf" in cmd
                assert any("test-model.gguf" in arg for arg in cmd)
                assert "--host" in cmd
                assert "1.2.3.4" in cmd
                assert "--port" in cmd
                assert "5555" in cmd
                assert "--ctx-size" in cmd
                assert "2048" in cmd
                assert "-ngl" in cmd
                assert "30" in cmd


@patch("local_ai_brain.models.llm_server.configure_logging")
@patch("os.environ", {"LOCAL_API_KEY": "test-api-key"})  # pragma: allowlist secret
@patch("os.execvp")
def test_main_config_alt_format(mock_exec, mock_log):
    """Verify that main() handles alternative YAML formats (direct dict)."""
    from local_ai_brain.models.llm_server import main

    yaml_content = """
model: "direct-model.gguf"
n_ctx: 1024
"""
    with patch("builtins.open", mock_open(read_data=yaml_content)):
        with patch("local_ai_brain.models.llm_server.Path.exists", return_value=True):
            with patch("sys.argv", ["llm_server"]):
                main()
                mock_exec.assert_called_once()
                cmd = mock_exec.call_args[0][1]
                assert "-hf" in cmd
                assert any("direct-model.gguf" in arg for arg in cmd)
                assert "--ctx-size" in cmd
                assert "1024" in cmd


@patch("local_ai_brain.models.llm_server.configure_logging")
@patch("os.execvp")
def test_main_no_config(mock_exec, mock_log):
    """Verify that main() uses defaults when no config file exists."""
    from local_ai_brain.models.llm_server import main

    with patch("local_ai_brain.models.llm_server.Path.exists", return_value=False):
        with patch("sys.argv", ["llm_server"]):
            main()
            mock_exec.assert_called_once()
            cmd = mock_exec.call_args[0][1]
            assert "-hf" in cmd
            assert "unsloth/Qwen3.6-35B-A3B-MTP-GGUF:*UD-Q4_K_M*" in cmd
            assert "--ctx-size" in cmd
            assert "98304" in cmd


@patch("local_ai_brain.models.llm_server.configure_logging")
@patch("os.execvp")
def test_main_exec_failure(mock_exec, mock_log):
    """Verify that main() exits with status 1 if execvp fails."""
    from local_ai_brain.models.llm_server import main

    mock_exec.side_effect = Exception("exec failed")
    with patch("local_ai_brain.models.llm_server.Path.exists", return_value=False):
        with patch("sys.argv", ["llm_server"]):
            with pytest.raises(SystemExit) as excinfo:
                main()
            assert excinfo.value.code == 1
