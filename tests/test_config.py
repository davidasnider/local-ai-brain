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

    import builtins
    from pathlib import Path

    orig_exists = Path.exists
    orig_open = builtins.open

    def mock_exists(self):
        if self.name == "llm_config.yaml":
            return orig_exists(tmp_path / "llm_config.yaml")
        return orig_exists(self)

    def mock_open_fn(file, mode="r", *args, **kwargs):
        if isinstance(file, (str, Path)) and str(file).endswith("llm_config.yaml"):
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
