import os

# Set testing environment variables before importing config
os.environ["LOCAL_API_KEY"] = "test-api-key"  # pragma: allowlist secret

import pytest
from pydantic import ValidationError

from local_ai_brain.config import Settings


@pytest.fixture(autouse=True)
def mock_llm_config_path(tmp_path, monkeypatch, request):
    if "tmp_path" not in request.fixturenames:
        return
    if request.node.name == "test_get_config_path_resolution":
        return

    import builtins
    from pathlib import Path

    orig_exists = Path.exists
    orig_open = builtins.open

    # Find the expected project root config path relative to tests directory
    test_dir = Path(__file__).resolve().parent
    real_project_root = test_dir
    for parent in [test_dir] + list(test_dir.parents):
        if (parent / "pyproject.toml").exists() or (parent / "llm_config.yaml").exists():
            real_project_root = parent
            break
    expected_config_path = (real_project_root / "llm_config.yaml").resolve()

    def mock_exists(self):
        try:
            resolved_self = self.resolve()
        except Exception:
            resolved_self = self
        if resolved_self == expected_config_path:
            return orig_exists(tmp_path / "llm_config.yaml")
        return orig_exists(self)

    def mock_open_fn(file, mode="r", *args, **kwargs):
        try:
            resolved_file = Path(file).resolve()
        except Exception:
            resolved_file = Path(file)
        if resolved_file == expected_config_path:
            return orig_open(tmp_path / "llm_config.yaml", mode, *args, **kwargs)
        return orig_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", mock_exists)
    monkeypatch.setattr(builtins, "open", mock_open_fn)


def test_settings_validation():
    # Valid settings — ensures Settings can be constructed with minimal config
    settings = Settings(LOCAL_API_KEY="test")  # pragma: allowlist secret
    assert settings.LOCAL_API_KEY == "test"  # pragma: allowlist secret
    assert settings.MAX_CONTEXT_TOKENS == 98304
    assert settings.DEFAULT_MAX_TOKENS == 16384


def test_settings_ignores_extra_fields():
    # Verify the Settings class ignores extra/unknown fields
    settings = Settings(
        LOCAL_API_KEY="test",  # pragma: allowlist secret
        LLM_KV_CACHE_BITS=4,
        UNSUPPORTED_PARAMETER="value",
    )
    assert settings.LOCAL_API_KEY == "test"  # pragma: allowlist secret
    assert not hasattr(settings, "LLM_KV_CACHE_BITS")
    assert not hasattr(settings, "UNSUPPORTED_PARAMETER")


def test_settings_max_tokens_validation():
    # Invalid: DEFAULT_MAX_TOKENS > MAX_CONTEXT_TOKENS
    with pytest.raises(ValidationError) as excinfo:
        Settings(
            LOCAL_API_KEY="test",  # pragma: allowlist secret
            DEFAULT_MAX_TOKENS=100,
            MAX_CONTEXT_TOKENS=50,
        )
    assert "DEFAULT_MAX_TOKENS" in str(excinfo.value)


def test_active_model_match_updates_qwen_model_path(tmp_path, monkeypatch):
    """When active_model matches a model profile in llm_config.yaml,
    QWEN_MODEL_PATH should be set from that profile."""
    import yaml

    config = {
        "active_model": "qwen-27b",
        "models": [
            {
                "name": "qwen-35b",
                "hf_model_repo_id": "unsloth/Qwen3.6-35B-MTP-GGUF",
                "model": "UD-Q4_K_M",
            },
            {
                "name": "qwen-27b",
                "hf_model_repo_id": "unsloth/Qwen3.6-27B-MTP-GGUF",
                "model": "UD-Q4_K_XL",
            },
        ],
    }
    config_path = tmp_path / "llm_config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    monkeypatch.chdir(tmp_path)
    settings = Settings(LOCAL_API_KEY="test")  # pragma: allowlist secret
    assert settings.QWEN_MODEL_PATH == "unsloth/Qwen3.6-27B-MTP-GGUF:UD-Q4_K_XL"


def test_active_model_not_found_falls_back_to_first(tmp_path, monkeypatch):
    """When active_model doesn't match any model name, fall back to the
    first model in the list (matching llm_server.py's behavior)."""
    import yaml

    config = {
        "active_model": "nonexistent-model",
        "models": [
            {
                "name": "qwen-35b",
                "hf_model_repo_id": "unsloth/Qwen3.6-35B-MTP-GGUF",
                "model": "UD-Q4_K_M",
            },
            {
                "name": "qwen-27b",
                "hf_model_repo_id": "unsloth/Qwen3.6-27B-MTP-GGUF",
                "model": "UD-Q4_K_XL",
            },
        ],
    }
    config_path = tmp_path / "llm_config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    monkeypatch.chdir(tmp_path)
    settings = Settings(LOCAL_API_KEY="test")  # pragma: allowlist secret
    # Should fall back to first model
    assert settings.QWEN_MODEL_PATH == "unsloth/Qwen3.6-35B-MTP-GGUF:UD-Q4_K_M"


def test_no_active_model_uses_first_model(tmp_path, monkeypatch):
    """When there's no active_model key but models list exists,
    use the first model (matching llm_server.py's behavior)."""
    import yaml

    config = {
        "models": [
            {
                "name": "qwen-35b",
                "hf_model_repo_id": "unsloth/Qwen3.6-35B-MTP-GGUF",
                "model": "UD-Q4_K_M",
            },
            {
                "name": "qwen-27b",
                "hf_model_repo_id": "unsloth/Qwen3.6-27B-MTP-GGUF",
                "model": "UD-Q4_K_XL",
            },
        ],
    }
    config_path = tmp_path / "llm_config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    monkeypatch.chdir(tmp_path)
    settings = Settings(LOCAL_API_KEY="test")  # pragma: allowlist secret
    assert settings.QWEN_MODEL_PATH == "unsloth/Qwen3.6-35B-MTP-GGUF:UD-Q4_K_M"


def test_env_qwen_model_path_takes_precedence(tmp_path, monkeypatch):
    """When QWEN_MODEL_PATH is set via environment, the YAML config
    should NOT override it."""
    import yaml

    config = {
        "active_model": "qwen-27b",
        "models": [
            {
                "name": "qwen-27b",
                "hf_model_repo_id": "unsloth/Qwen3.6-27B-MTP-GGUF",
                "model": "UD-Q4_K_XL",
            },
        ],
    }
    config_path = tmp_path / "llm_config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("QWEN_MODEL_PATH", "custom/repo:custom-file")
    settings = Settings(LOCAL_API_KEY="test")  # pragma: allowlist secret
    # Env var should take precedence over YAML config
    assert settings.QWEN_MODEL_PATH == "custom/repo:custom-file"


def test_local_model_resolution(tmp_path, monkeypatch):
    import yaml

    config = {
        "active_model": "qwen-local",
        "models": [
            {
                "name": "qwen-local",
                "hf_model_repo_id": "",
                "model": "/path/to/local/model.gguf",
            },
        ],
    }
    config_path = tmp_path / "llm_config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    monkeypatch.chdir(tmp_path)
    settings = Settings(LOCAL_API_KEY="test")  # pragma: allowlist secret
    assert settings.QWEN_MODEL_PATH == "/path/to/local/model.gguf"

    # Also test first fallback without active_model
    config2 = {
        "models": [
            {
                "name": "qwen-local",
                "hf_model_repo_id": "",
                "model": "/path/to/local/model.gguf",
            },
        ],
    }
    with open(config_path, "w") as f:
        yaml.dump(config2, f)
    settings = Settings(LOCAL_API_KEY="test")  # pragma: allowlist secret
    assert settings.QWEN_MODEL_PATH == "/path/to/local/model.gguf"


def test_legacy_flat_config_handling(tmp_path, monkeypatch):
    import yaml

    config = {
        "hf_model_repo_id": "test-repo",
        "model": "test-model.gguf",
    }
    config_path = tmp_path / "llm_config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    monkeypatch.chdir(tmp_path)
    settings = Settings(LOCAL_API_KEY="test")  # pragma: allowlist secret
    assert settings.QWEN_MODEL_PATH == "test-repo:test-model.gguf"


def test_get_config_path_resolution():
    """Verify that get_config_path resolves to the repository root relative to the source file."""
    from pathlib import Path

    from local_ai_brain.config import get_config_path

    start_path = Path(__file__).resolve()
    current = start_path.parent
    expected_root = None
    for parent in [current] + list(current.parents):
        if (parent / "pyproject.toml").exists():
            expected_root = parent
            break

    assert expected_root is not None
    expected_path = expected_root / "llm_config.yaml"

    assert get_config_path(start_path) == expected_path


def test_get_config_path_empty_string():
    """Verify that get_config_path with an empty string or None resolves using __file__."""
    from local_ai_brain.config import get_config_path

    path_from_empty = get_config_path("")
    path_from_none = get_config_path(None)

    assert path_from_empty == path_from_none


def test_malformed_config_structure_fails_fast(tmp_path, monkeypatch):
    """When llm_config.yaml has a malformed structure, it should fail fast on startup."""
    import yaml

    config = {
        "active_model": "qwen-27b",
        "models": "not_a_list",
    }
    config_path = tmp_path / "llm_config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValidationError) as excinfo:
        Settings(LOCAL_API_KEY="test")  # pragma: allowlist secret

    assert "Invalid llm_config.yaml structure" in str(excinfo.value)


def test_syntax_broken_config_fails_fast(tmp_path, monkeypatch):
    """When llm_config.yaml is syntax-broken, it should fail fast on startup with a ValueError."""
    config_path = tmp_path / "llm_config.yaml"
    with open(config_path, "w") as f:
        f.write("active_model: [unclosed_bracket")

    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValidationError) as excinfo:
        Settings(LOCAL_API_KEY="test")  # pragma: allowlist secret

    assert "Syntax error in llm_config.yaml" in str(excinfo.value)


def test_config_file_not_found_during_open(tmp_path, monkeypatch):
    """When open() raises FileNotFoundError, it should log a warning instead of failing fast."""
    from unittest.mock import patch

    # Force config_path to exist so it attempts to open it
    config_path = tmp_path / "llm_config.yaml"
    with open(config_path, "w") as f:
        f.write("active_model: dummy")

    monkeypatch.chdir(tmp_path)

    # Mock builtins.open to raise FileNotFoundError only when opening the config file
    import builtins

    orig_open = builtins.open

    def mock_open_fn(file, *args, **kwargs):
        if str(file).endswith("llm_config.yaml"):
            raise FileNotFoundError("Mocked file not found")
        return orig_open(file, *args, **kwargs)

    with patch("builtins.open", mock_open_fn):
        settings = Settings(LOCAL_API_KEY="test")  # pragma: allowlist secret
        # Check that it fell back to the default instead of crashing
        assert settings.LOCAL_API_KEY == "test"  # pragma: allowlist secret


def test_non_dict_config_fails_fast(tmp_path, monkeypatch):
    """Fail fast with ValueError if llm_config.yaml is a non-dictionary (like a list)."""
    config_path = tmp_path / "llm_config.yaml"
    with open(config_path, "w") as f:
        f.write("- model: qwen\n  name: qwen-list\n")

    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValidationError) as excinfo:
        Settings(LOCAL_API_KEY="test")  # pragma: allowlist secret

    assert "llm_config.yaml must be a mapping, got list" in str(excinfo.value)
