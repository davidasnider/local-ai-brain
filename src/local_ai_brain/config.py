from pathlib import Path
from typing import Optional

from loguru import logger
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def get_config_path(start_path: Optional[Path | str] = None) -> Path:
    """Find the path to llm_config.yaml by walking up from the start_path."""
    if start_path is None or start_path == "":
        start_path = Path(__file__)
    current = Path(start_path).resolve()
    if current.is_file():
        current = current.parent
    for parent in [current] + list(current.parents):
        if (parent / "pyproject.toml").exists() or (parent / "llm_config.yaml").exists():
            return parent / "llm_config.yaml"
    return current / "llm_config.yaml"


class Settings(BaseSettings):
    # Core settings
    LOCAL_API_KEY: str
    TTS_MAX_CHARACTERS: int = Field(default=4096, gt=0)
    MAX_CONTEXT_TOKENS: int = Field(default=98304, gt=0)
    DEFAULT_MAX_TOKENS: int = Field(default=16384, gt=0)
    TESTING: bool = False
    LOG_PROMPTS: bool = False

    # Microservices URLs
    VLLM_URL: str = "http://127.0.0.1:8001"
    STT_URL: str = "http://127.0.0.1:8002"
    TTS_URL: str = "http://127.0.0.1:8003"

    # Hugging Face token (optional, for private or rate‑limited repos)
    HF_TOKEN: Optional[str] = Field(default=None, validation_alias="HF_TOKEN")

    # Model paths
    QWEN_MODEL_PATH: str = "unsloth/Qwen3.6-27B-MTP-GGUF:UD-Q4_K_XL"
    WHISPER_MODEL_PATH: str = "mlx-community/whisper-large-v3-mlx"
    KOKORO_MODEL_PATH: str = "kokoro-onnx"
    KOKORO_HF_REPO: str = "fastrtc/kokoro-onnx"
    KOKORO_ONNX_FILE: str = "kokoro-v1.0.onnx"
    KOKORO_VOICES_FILE: str = "voices-v1.0.bin"

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

    @model_validator(mode="after")
    def _validate_and_load_config(self) -> "Settings":
        try:
            import yaml

            if "QWEN_MODEL_PATH" not in self.model_fields_set:
                config_path = get_config_path(__file__)
                if config_path.exists():
                    with open(config_path, "r") as f:
                        loaded = yaml.safe_load(f)
                        if (
                            isinstance(loaded, dict)
                            and "active_model" in loaded
                            and "models" in loaded
                        ):
                            active = loaded["active_model"]
                            matched = None
                            for m in loaded["models"]:
                                if m.get("name") == active:
                                    matched = m
                                    break
                            # Fall back to first model if active_model not found
                            if matched is None and len(loaded["models"]) > 0:
                                matched = loaded["models"][0]
                            if matched:
                                repo = matched.get("hf_model_repo_id", "")
                                model_file = matched.get("model", "")
                                if model_file:
                                    self.QWEN_MODEL_PATH = (
                                        f"{repo}:{model_file}" if repo else model_file
                                    )
                        elif (
                            isinstance(loaded, dict)
                            and "models" in loaded
                            and len(loaded["models"]) > 0
                        ):
                            # No active_model key — use first model
                            first = loaded["models"][0]
                            repo = first.get("hf_model_repo_id", "")
                            model_file = first.get("model", "")
                            if model_file:
                                self.QWEN_MODEL_PATH = (
                                    f"{repo}:{model_file}" if repo else model_file
                                )
                        elif isinstance(loaded, dict) and "models" not in loaded:
                            repo = loaded.get("hf_model_repo_id", "")
                            model_file = loaded.get("model", "")
                            if model_file:
                                self.QWEN_MODEL_PATH = (
                                    f"{repo}:{model_file}" if repo else model_file
                                )
        except Exception as e:
            logger.warning(f"Failed to load active model from llm_config.yaml: {e}")

        if self.DEFAULT_MAX_TOKENS > self.MAX_CONTEXT_TOKENS:
            raise ValueError(
                f"DEFAULT_MAX_TOKENS ({self.DEFAULT_MAX_TOKENS}) cannot exceed "
                f"MAX_CONTEXT_TOKENS ({self.MAX_CONTEXT_TOKENS})"
            )
        return self

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
