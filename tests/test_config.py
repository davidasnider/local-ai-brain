import pytest
from pydantic import ValidationError

from local_ai_brain.config import Settings


def test_settings_validation():
    # Valid settings
    Settings(LOCAL_API_KEY="test")  # pragma: allowlist secret


def test_settings_max_tokens_validation():
    # Invalid: DEFAULT_MAX_TOKENS > MAX_CONTEXT_TOKENS
    with pytest.raises(ValidationError) as excinfo:
        Settings(
            LOCAL_API_KEY="test",  # pragma: allowlist secret
            DEFAULT_MAX_TOKENS=100,
            MAX_CONTEXT_TOKENS=50,
        )
    assert "DEFAULT_MAX_TOKENS" in str(excinfo.value)
