from typing import Optional

from loguru import logger
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Core settings
    LOCAL_API_KEY: str
    MEMORY_LIMIT_GB: float = Field(default=54.0, gt=0)
    TTS_MAX_CHARACTERS: int = Field(default=4096, gt=0)
    MAX_CONTEXT_TOKENS: int = Field(default=65536, gt=0)
    DEFAULT_MAX_TOKENS: int = Field(default=16384, gt=0)
    TESTING: bool = False

    # Hugging Face token (optional, for private or rate‑limited repos)
    HF_TOKEN: Optional[str] = Field(default=None, validation_alias="HF_TOKEN")

    # Model paths
    QWEN_MODEL_PATH: str = "mlx-community/Qwen3.6-35B-A3B-4bit"
    WHISPER_MODEL_PATH: str = "mlx-community/whisper-large-v3-mlx"
    KOKORO_MODEL_PATH: str = "kokoro-onnx"
    KOKORO_HF_REPO: str = "fastrtc/kokoro-onnx"
    KOKORO_ONNX_FILE: str = "kokoro-v1.0.onnx"
    KOKORO_VOICES_FILE: str = "voices-v1.0.bin"

    # LLM engine settings
    LLM_KV_CACHE_QUANTIZATION: bool = True
    LLM_KV_CACHE_BITS: int = Field(default=4, ge=4, le=8)

    # Legacy model ID aliases (accepted in addition to QWEN_MODEL_PATH)
    QWEN_MODEL_ALIASES: list[str] = Field(default=["mlx-community/Qwen3.6-35B-A3B-8bit"])

    @field_validator("LOCAL_API_KEY", mode="before")
    @classmethod
    def _validate_api_key(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            raise ValueError("LOCAL_API_KEY is required (set env var or .env)")
        return v

    @field_validator("HF_TOKEN", mode="before")
    @classmethod
    def _validate_hf_token(cls, v: Optional[str]) -> Optional[str]:
        normalized = v
        if isinstance(normalized, str):
            normalized = normalized.strip() or None

        if normalized is None:
            logger.warning("HF_TOKEN not set; downloads may be slow or rate‑limited.")

        return normalized

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
