import pytest
from pydantic import ValidationError

from local_ai_brain.config import Settings


def test_settings_validation():
    # Valid settings
    settings = Settings(LOCAL_API_KEY="test")  # pragma: allowlist secret
    assert settings.LLM_PREFILL_STEP_SIZE == 128
    assert settings.LLM_MAX_NUM_SEQS == 1

    # Invalid LLM_PREFILL_STEP_SIZE (zero)
    with pytest.raises(ValidationError) as excinfo:
        Settings(LOCAL_API_KEY="test", LLM_PREFILL_STEP_SIZE=0)  # pragma: allowlist secret
    assert "LLM_PREFILL_STEP_SIZE" in str(excinfo.value)
    assert "greater than 0" in str(excinfo.value)

    # Invalid LLM_MAX_NUM_SEQS (negative)
    with pytest.raises(ValidationError) as excinfo:
        Settings(LOCAL_API_KEY="test", LLM_MAX_NUM_SEQS=-1)  # pragma: allowlist secret
    assert "LLM_MAX_NUM_SEQS" in str(excinfo.value)
    assert "greater than 0" in str(excinfo.value)


def test_settings_max_tokens_validation():
    # Invalid: DEFAULT_MAX_TOKENS > MAX_CONTEXT_TOKENS
    with pytest.raises(ValidationError) as excinfo:
        Settings(
            LOCAL_API_KEY="test",  # pragma: allowlist secret
            DEFAULT_MAX_TOKENS=100,
            MAX_CONTEXT_TOKENS=50,
        )
    assert "DEFAULT_MAX_TOKENS" in str(excinfo.value)
