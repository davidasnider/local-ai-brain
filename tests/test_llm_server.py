import os
from pathlib import Path
from unittest.mock import mock_open, patch

import pytest

# Set dummy env vars for module-level settings imports in some modules
os.environ.setdefault("LOCAL_API_KEY", "test-api-key")
os.environ.setdefault("TESTING", "1")

from local_ai_brain.config import settings


@patch("local_ai_brain.models.llm_server.configure_logging")
@patch.dict("os.environ", {"LOCAL_API_KEY": "test-api-key"})  # pragma: allowlist secret
@patch("os.execvp")
def test_main_success(mock_exec, mock_log, monkeypatch):
    """Verify that main() builds the correct command and calls execvp."""
    from local_ai_brain.models.llm_server import main

    yaml_content = """
models:
  - model: "test-model.gguf"
    n_ctx: 2048
    n_gpu_layers: 30
"""
    monkeypatch.setattr(Path, "exists", lambda self: self.name == "llm_config.yaml")
    with patch("builtins.open", mock_open(read_data=yaml_content)):
        # Mock sys.argv to simulate CLI overrides
        with patch("sys.argv", ["llm_server", "--host", "1.2.3.4", "--port", "5555"]):
            main()

            mock_exec.assert_called_once()
            args = mock_exec.call_args[0]
            assert args[0] == "llama-server"
            cmd = args[1]
            assert "--model" in cmd
            assert "-hf" not in cmd
            assert any("test-model.gguf" in arg for arg in cmd)
            assert "--host" in cmd
            assert "1.2.3.4" in cmd
            assert "--port" in cmd
            assert "5555" in cmd
            assert "--ctx-size" in cmd
            assert "2048" in cmd
            assert "-ngl" in cmd
            assert "30" in cmd
            assert os.environ.get("LLAMA_API_KEY") == "test-api-key"


@patch("local_ai_brain.models.llm_server.configure_logging")
@patch.dict("os.environ", {"LOCAL_API_KEY": "test-api-key"})  # pragma: allowlist secret
@patch("os.execvp")
def test_main_config_alt_format(mock_exec, mock_log, monkeypatch):
    """Verify that main() handles alternative YAML formats (direct dict)."""
    from local_ai_brain.models.llm_server import main

    yaml_content = """
model: "direct-model.gguf"
n_ctx: 1024
"""
    monkeypatch.setattr(Path, "exists", lambda self: self.name == "llm_config.yaml")
    with patch("builtins.open", mock_open(read_data=yaml_content)):
        with patch("sys.argv", ["llm_server"]):
            main()
            mock_exec.assert_called_once()
            cmd = mock_exec.call_args[0][1]
            assert "--model" in cmd
            assert "-hf" not in cmd
            assert any("direct-model.gguf" in arg for arg in cmd)
            assert "--ctx-size" in cmd
            assert "1024" in cmd


@patch("local_ai_brain.models.llm_server.configure_logging")
@patch("os.execvp")
def test_main_no_config(mock_exec, mock_log, monkeypatch):
    """Verify that main() uses defaults when no config file exists."""
    from local_ai_brain.models.llm_server import main

    # Pin the expected default so a real llm_config.yaml at repo root
    # cannot override QWEN_MODEL_PATH via the Settings singleton.
    settings.QWEN_MODEL_PATH = "unsloth/Qwen3.6-27B-MTP-GGUF:UD-Q4_K_XL"

    monkeypatch.setattr(Path, "exists", lambda self: False)
    with patch("sys.argv", ["llm_server"]):
        main()
        mock_exec.assert_called_once()
        cmd = mock_exec.call_args[0][1]
        assert "-hf" in cmd
        assert "unsloth/Qwen3.6-27B-MTP-GGUF:UD-Q4_K_XL" in cmd
        assert "--ctx-size" in cmd
        assert "98304" in cmd


@patch("local_ai_brain.models.llm_server.configure_logging")
@patch.dict("os.environ", {"LOCAL_API_KEY": "test-api-key"})  # pragma: allowlist secret
@patch("os.execvp")
def test_main_config_speculative_params(mock_exec, mock_log, monkeypatch):
    """Verify that main() parses speculative parameters from config."""
    from local_ai_brain.models.llm_server import main

    yaml_content = """
model: "direct-model.gguf"
n_parallel: 2
spec_type: "draft-mtp"
spec_draft_n_max: 3
spec_draft_p_min: 0.8
"""
    monkeypatch.setattr(Path, "exists", lambda self: self.name == "llm_config.yaml")
    with patch("builtins.open", mock_open(read_data=yaml_content)):
        with patch("sys.argv", ["llm_server"]):
            main()
            mock_exec.assert_called_once()
            cmd = mock_exec.call_args[0][1]

            def get_val(flag):
                try:
                    idx = cmd.index(flag)
                    return cmd[idx + 1]
                except (ValueError, IndexError):
                    return None

            assert get_val("-np") == "2"
            assert get_val("--spec-type") == "draft-mtp"
            assert get_val("--spec-draft-n-max") == "3"
            assert get_val("--spec-draft-p-min") == "0.8"


@patch("local_ai_brain.models.llm_server.configure_logging")
@patch("os.execvp")
def test_main_exec_failure(mock_exec, mock_log, monkeypatch):
    """Verify that main() exits with status 1 if execvp fails."""
    from local_ai_brain.models.llm_server import main

    mock_exec.side_effect = Exception("exec failed")
    monkeypatch.setattr(Path, "exists", lambda self: False)
    with patch("sys.argv", ["llm_server"]):
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 1


@patch("local_ai_brain.models.llm_server.configure_logging")
@patch("os.execvp")
def test_main_active_model_selection(mock_exec, mock_log, monkeypatch):
    """Verify that main() selects the active model from list of models."""
    from local_ai_brain.models.llm_server import main

    yaml_content = """
active_model: "qwen-27b"
models:
  - name: "qwen-35b"
    hf_model_repo_id: "unsloth/Qwen3.6-35B-MTP-GGUF"
    model: "UD-Q4_K_M"
    n_ctx: 1024
  - name: "qwen-27b"
    hf_model_repo_id: "unsloth/Qwen3.6-27B-MTP-GGUF"
    model: "UD-Q4_K_XL"
    n_ctx: 2048
"""
    monkeypatch.setattr(Path, "exists", lambda self: self.name == "llm_config.yaml")
    with patch("builtins.open", mock_open(read_data=yaml_content)):
        with patch("sys.argv", ["llm_server"]):
            main()
            mock_exec.assert_called_once()
            cmd = mock_exec.call_args[0][1]
            assert any("UD-Q4_K_XL" in arg for arg in cmd)
            assert "--ctx-size" in cmd
            assert "2048" in cmd


@patch("local_ai_brain.models.llm_server.configure_logging")
@patch("os.execvp")
def test_main_active_model_fallback(mock_exec, mock_log, monkeypatch):
    """Verify that main() falls back to first model if active_model is not found."""
    from local_ai_brain.models.llm_server import main

    yaml_content = """
active_model: "nonexistent"
models:
  - name: "qwen-35b"
    hf_model_repo_id: "unsloth/Qwen3.6-35B-MTP-GGUF"
    model: "UD-Q4_K_M"
    n_ctx: 1024
  - name: "qwen-27b"
    hf_model_repo_id: "unsloth/Qwen3.6-27B-MTP-GGUF"
    model: "UD-Q4_K_XL"
    n_ctx: 2048
"""
    monkeypatch.setattr(Path, "exists", lambda self: self.name == "llm_config.yaml")
    with patch("builtins.open", mock_open(read_data=yaml_content)):
        with patch("sys.argv", ["llm_server"]):
            main()
            mock_exec.assert_called_once()
            cmd = mock_exec.call_args[0][1]
            assert any("UD-Q4_K_M" in arg for arg in cmd)
            assert "--ctx-size" in cmd
            assert "1024" in cmd


@patch("local_ai_brain.models.llm_server.configure_logging")
@patch("os.execvp")
def test_main_invalid_yaml(mock_exec, mock_log, monkeypatch):
    """Verify that main() exits with 1 when YAML parsing fails."""
    from local_ai_brain.models.llm_server import main

    yaml_content = "invalid_yaml: ["
    monkeypatch.setattr(Path, "exists", lambda self: self.name == "llm_config.yaml")
    with patch("builtins.open", mock_open(read_data=yaml_content)):
        with patch("sys.argv", ["llm_server"]):
            with pytest.raises(SystemExit) as excinfo:
                main()
            assert excinfo.value.code == 1


@patch("local_ai_brain.models.llm_server.configure_logging")
@patch("os.execvp")
def test_main_binary_not_found(mock_exec, mock_log, monkeypatch):
    """Verify that main() exits with 1 and logs error when llama-server binary is not found."""
    from local_ai_brain.models.llm_server import main

    mock_exec.side_effect = FileNotFoundError()
    monkeypatch.setattr(Path, "exists", lambda self: False)
    with patch("sys.argv", ["llm_server"]):
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 1


@patch("local_ai_brain.models.llm_server.configure_logging")
@patch("os.execvp")
def test_main_cache_quantization_and_local_fallback(mock_exec, mock_log, monkeypatch):
    """Verify cache type quantization mapping and local model resolution fallback logic."""
    from local_ai_brain.models.llm_server import main

    yaml_content = """
models:
  - name: "local-model"
    model: "/path/to/local/model.gguf"
    type_k: 8
    type_v: "q8_0"
"""
    monkeypatch.setattr(Path, "exists", lambda self: self.name == "llm_config.yaml")
    with patch("builtins.open", mock_open(read_data=yaml_content)):
        with patch("sys.argv", ["llm_server"]):
            main()
            mock_exec.assert_called_once()
            cmd = mock_exec.call_args[0][1]
            # It should use --model and not -hf
            assert "-hf" not in cmd
            assert "--model" in cmd
            assert "/path/to/local/model.gguf" in cmd
            # It should map type_k and pass through type_v correctly
            assert "--cache-type-k" in cmd
            assert cmd[cmd.index("--cache-type-k") + 1] == "q8_0"
            assert "--cache-type-v" in cmd
            assert cmd[cmd.index("--cache-type-v") + 1] == "q8_0"


@patch("local_ai_brain.models.llm_server.configure_logging")
@patch("os.execvp")
def test_main_local_model_explicit_empty_repo(mock_exec, mock_log, monkeypatch):
    """Verify local model resolution when hf_model_repo_id is explicitly empty."""
    from local_ai_brain.models.llm_server import main

    yaml_content = """
models:
  - name: "local-model"
    hf_model_repo_id: ""
    model: "model.gguf"
"""
    monkeypatch.setattr(Path, "exists", lambda self: self.name == "llm_config.yaml")
    with patch("builtins.open", mock_open(read_data=yaml_content)):
        with patch("sys.argv", ["llm_server"]):
            main()
            mock_exec.assert_called_once()
            cmd = mock_exec.call_args[0][1]
            assert "-hf" not in cmd
            assert "--model" in cmd
            assert "model.gguf" in cmd


@patch("local_ai_brain.models.llm_server.configure_logging")
@patch("os.execvp")
def test_main_local_model_exists_on_disk(mock_exec, mock_log, monkeypatch):
    """Verify local model resolution when model file exists on disk."""
    from local_ai_brain.models.llm_server import main

    yaml_content = """
models:
  - name: "local-model"
    model: "existing_model.gguf"
"""
    # We mock exists such that config_path.exists() is True (which is called for llm_config.yaml)
    # and Path("existing_model.gguf").exists() is True
    monkeypatch.setattr(
        Path,
        "exists",
        lambda self: self.name in ("llm_config.yaml", "existing_model.gguf"),
    )
    with patch("builtins.open", mock_open(read_data=yaml_content)):
        with patch("sys.argv", ["llm_server"]):
            main()
            mock_exec.assert_called_once()
            cmd = mock_exec.call_args[0][1]
            assert "-hf" not in cmd
            assert "--model" in cmd
            assert "existing_model.gguf" in cmd


@patch("local_ai_brain.models.llm_server.configure_logging")
@patch("os.execvp")
def test_main_local_model_relative_path_slash(mock_exec, mock_log, monkeypatch):
    """Verify local model resolution when model is a relative path containing a slash."""
    from local_ai_brain.models.llm_server import main

    yaml_content = """
models:
  - name: "local-model"
    model: "models/qwen.gguf"
"""
    monkeypatch.setattr(
        Path,
        "exists",
        lambda self: self.name in ("llm_config.yaml", "qwen.gguf"),
    )
    with patch("builtins.open", mock_open(read_data=yaml_content)):
        with patch("sys.argv", ["llm_server"]):
            main()
            mock_exec.assert_called_once()
            cmd = mock_exec.call_args[0][1]
            assert "-hf" not in cmd
            assert "--model" in cmd
            assert "models/qwen.gguf" in cmd


def test_build_command_api_key_fallback_to_settings(monkeypatch):
    """Verify that build_command falls back to settings.LOCAL_API_KEY when env keys are missing."""
    from local_ai_brain.config import settings
    from local_ai_brain.models.llm_server import build_command

    # Ensure environment does not contain the keys
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LOCAL_API_KEY", raising=False)
    monkeypatch.delenv("LLAMA_API_KEY", raising=False)

    # Set the fallback value on settings
    monkeypatch.setattr(settings, "LOCAL_API_KEY", "fallback-secret-key")

    # Call build_command
    build_command({}, "127.0.0.1", "8001")

    # Verify that LLAMA_API_KEY is set to settings.LOCAL_API_KEY
    assert os.environ.get("LLAMA_API_KEY") == "fallback-secret-key"


def test_build_command_tilde_expansion():
    """Verify that build_command expands tilde (~) paths before executing llama-server."""
    from local_ai_brain.models.llm_server import build_command

    config = {"model": "~/models/my_model.gguf"}
    cmd = build_command(config, "127.0.0.1", "8001")

    # It should not contain '~' in the --model or --alias arguments
    assert "~/models/my_model.gguf" not in cmd

    # It should contain the expanded path
    expected_path = os.path.expanduser("~/models/my_model.gguf")
    assert expected_path in cmd
    assert cmd[cmd.index("--model") + 1] == expected_path
    assert cmd[cmd.index("--alias") + 1] == expected_path


def test_is_local_path_has_fs_characteristics():
    """Verify that models with FS characteristics are treated as local if they do not exist."""
    from local_ai_brain.models.llm_server import build_command

    # Using a model name that doesn't exist and ends in .gguf
    config = {"model": "nonexistent_model_with_fs_characteristics.gguf"}
    cmd = build_command(config, "127.0.0.1", "8001")

    # It should build command using --model, not -hf
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "nonexistent_model_with_fs_characteristics.gguf"
    assert "-hf" not in cmd
