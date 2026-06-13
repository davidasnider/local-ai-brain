import os

# Set testing environment variables before importing config
os.environ["LOCAL_API_KEY"] = "test-api-key"  # pragma: allowlist secret

import pytest
from pydantic import ValidationError

from local_ai_brain.config import Settings


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
