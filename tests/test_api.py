import os
import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# Set environment variables BEFORE any imports from the app
os.environ["TESTING"] = "1"
os.environ["LOCAL_API_KEY"] = "test-secret-key"

# Mock heavy ML modules to prevent them from being imported/loaded at all
mock_vllm = MagicMock()
mock_batched = MagicMock()
mock_batched_instance = MagicMock()


async def dummy_async():
    pass


mock_batched_instance.start = dummy_async
mock_batched_instance.stop = dummy_async


# Mock for engine.chat
class MockOutput:
    def __init__(self):
        self.text = "Hello from mock!"
        self.prompt_tokens = 10
        self.completion_tokens = 20
        self.finish_reason = "stop"


async def mock_chat(*args, **kwargs):
    return MockOutput()


# Mock for engine.stream_chat
class MockChunk:
    def __init__(self, text, reason=None):
        self.new_text = text
        self.finish_reason = reason


async def mock_stream_chat(*args, **kwargs):
    yield MockChunk("Hello")
    yield MockChunk(" from")
    yield MockChunk(" mock!", "stop")


mock_batched_instance.chat = mock_chat
mock_batched_instance.stream_chat = mock_stream_chat
mock_batched.return_value = mock_batched_instance

mock_vllm.engine.batched.BatchedEngine = mock_batched
sys.modules["vllm_mlx"] = mock_vllm
sys.modules["vllm_mlx.engine"] = MagicMock()
sys.modules["vllm_mlx.engine.batched"] = MagicMock()
sys.modules["vllm_mlx.engine.batched"].BatchedEngine = mock_batched

# Mock vllm_mlx.scheduler with a real SchedulerConfig stub
mock_scheduler_module = MagicMock()


class MockSchedulerConfig:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


mock_scheduler_module.SchedulerConfig = MockSchedulerConfig
sys.modules["vllm_mlx.scheduler"] = mock_scheduler_module

mock_whisper = MagicMock()
mock_whisper.transcribe.return_value = {"text": "Hello from mock Whisper!"}
sys.modules["mlx_whisper"] = mock_whisper


# Kokoro TTS mock
class MockKokoro:
    def __init__(self, *args, **kwargs):
        pass

    def create(self, text, voice, speed=1.0):
        return np.zeros(24000), 24000


sys.modules["kokoro_onnx"] = MagicMock()
sys.modules["kokoro_onnx"].Kokoro = MockKokoro

mock_hf = MagicMock()
mock_hf.hf_hub_download.return_value = "/tmp/mock_model"
sys.modules["huggingface_hub"] = mock_hf
sys.modules["huggingface_hub.utils"] = MagicMock()

from fastapi.testclient import TestClient  # noqa: E402

from local_ai_brain.main import app  # noqa: E402


def test_health():
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer test-secret-key"}
        response = client.get("/health", headers=headers)
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


def test_metrics():
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer test-secret-key"}
        response = client.get("/metrics", headers=headers)
        assert response.status_code == 200
        assert "http_requests_total" in response.text


def test_logging_interceptor_error_paths():
    import logging

    # Trigger ValueError in level lookup
    logging.getLogger("test_unknown_level").log(99, "Test unknown level")

    # Trigger shallow stack depth for InterceptHandler
    from local_ai_brain.main import InterceptHandler

    handler = InterceptHandler()
    record = logging.LogRecord("name", logging.INFO, "pathname", 10, "msg", None, None)

    with patch("sys._getframe", side_effect=ValueError("Shallow stack")):
        handler.emit(record)


def test_configure_logging():
    from local_ai_brain.main import configure_logging

    with patch("os.path.expanduser", return_value="/tmp/test-log.log"):
        with patch("os.makedirs") as mock_makedirs:
            with patch("loguru.logger.add") as mock_logger_add:
                configure_logging(testing=False)
                mock_makedirs.assert_called_once_with("/tmp", exist_ok=True)
                mock_logger_add.assert_called_once()


def test_chat_completions_streaming_error():
    with TestClient(app) as client:
        client.app.state.llm_engine = mock_batched_instance
        # Mock stream_chat to raise an exception
        with patch.object(
            mock_batched_instance, "stream_chat", side_effect=Exception("Stream failed")
        ):
            headers = {"Authorization": "Bearer test-secret-key"}
            # TestClient with streaming might raise the exception during the post call
            # if it attempts to start the stream.
            with pytest.raises(Exception, match="Stream failed"):
                client.post(
                    "/v1/chat/completions",
                    json={"messages": [{"role": "user", "content": "hi"}], "stream": True},
                    headers=headers,
                )


def test_config_validators():
    from local_ai_brain.config import Settings

    # Test HF_TOKEN warning
    with patch("local_ai_brain.config.logger") as mock_logger:
        Settings(LOCAL_API_KEY="test", HF_TOKEN="")
        mock_logger.warning.assert_called_once()

    # Test missing LOCAL_API_KEY
    with pytest.raises(ValueError, match="LOCAL_API_KEY is required"):
        # We use mode='before' validator, so passing None or empty string should trigger it
        # if the field is required.
        Settings(LOCAL_API_KEY="")


def test_chat_completions_error():
    with TestClient(app) as client:
        client.app.state.llm_engine = mock_batched_instance
        # Mock chat to raise an exception
        with patch.object(mock_batched_instance, "chat", side_effect=Exception("Chat failed")):
            headers = {"Authorization": "Bearer test-secret-key"}
            response = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "hi"}]},
                headers=headers,
            )
            assert response.status_code == 500


def test_audio_speech_error():
    with TestClient(app) as client:
        mock_tts = MagicMock()
        mock_tts.create.side_effect = Exception("TTS failed")
        client.app.state.tts_model = mock_tts
        headers = {"Authorization": "Bearer test-secret-key"}
        response = client.post(
            "/v1/audio/speech",
            json={"input": "hello", "voice": "default"},
            headers=headers,
        )
        assert response.status_code == 500


def test_audio_transcription_error():
    with TestClient(app) as client:
        client.app.state.stt_model = mock_whisper
        with patch.object(mock_whisper, "transcribe", side_effect=Exception("Whisper failed")):
            headers = {"Authorization": "Bearer test-secret-key"}
            files = {"file": ("test.wav", b"fake-audio-data", "audio/wav")}
            response = client.post("/v1/audio/transcriptions", files=files, headers=headers)
            assert response.status_code == 500


def test_audio_transcription_duration_failure():
    with TestClient(app) as client:
        client.app.state.stt_model = mock_whisper
        # Mock sf.info to fail
        with patch("local_ai_brain.api.audio.sf.info", side_effect=Exception("Read failed")):
            headers = {"Authorization": "Bearer test-secret-key"}
            files = {"file": ("test.wav", b"fake-audio-data", "audio/wav")}
            response = client.post("/v1/audio/transcriptions", files=files, headers=headers)
            # Should still succeed as it logs warning and continues
            assert response.status_code == 200


def test_health_models_loaded():
    with TestClient(app) as client:
        client.app.state.llm_engine = mock_batched_instance
        headers = {"Authorization": "Bearer test-secret-key"}
        response = client.get("/health", headers=headers)
        assert response.status_code == 200
        assert response.json()["models_loaded"] is True


def test_unauthorized_access():
    with TestClient(app) as client:
        response = client.post("/v1/chat/completions", json={"messages": []})
        assert response.status_code in [401, 403]


def test_invalid_api_key():
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer bad-key"}
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers=headers,
        )
        assert response.status_code == 401


def test_chat_completions():
    with TestClient(app) as client:
        client.app.state.llm_engine = mock_batched_instance
        headers = {"Authorization": "Bearer test-secret-key"}
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers=headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert "id" in body
        assert isinstance(body["id"], str)
        assert body["id"].startswith("chatcmpl-")


def test_chat_completions_streaming():
    with TestClient(app) as client:
        client.app.state.llm_engine = mock_batched_instance
        headers = {"Authorization": "Bearer test-secret-key"}
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}], "stream": True},
            headers=headers,
        )
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]

        # Read the chunks
        lines = [
            line.decode("utf-8") if isinstance(line, bytes) else line
            for line in response.iter_lines()
            if line
        ]
        assert any("data: {" in line for line in lines)
        assert any("data: [DONE]" in line for line in lines)


def test_chat_engine_not_initialized():
    with TestClient(app) as client:
        client.app.state.llm_engine = None
        headers = {"Authorization": "Bearer test-secret-key"}
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers=headers,
        )
        assert response.status_code == 503


def test_batched_engine_receives_scheduler_config():
    """Verify lifespan() passes the correct SchedulerConfig to BatchedEngine."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from local_ai_brain.config import settings

    captured_kwargs = {}

    mock_engine_instance = MagicMock()
    mock_engine_instance.start = AsyncMock()
    mock_engine_instance.stop = AsyncMock()

    def capturing_engine_cls(model_name, scheduler_config=None, **kwargs):
        captured_kwargs["model_name"] = model_name
        captured_kwargs["scheduler_config"] = scheduler_config
        return mock_engine_instance

    mock_whisper_module = MagicMock()
    mock_kokoro_instance = MagicMock()
    mock_kokoro_instance.create = MagicMock(return_value=(b"", 24000))

    with (
        patch("local_ai_brain.main.settings.TESTING", False),
        patch("local_ai_brain.main.BatchedEngine", side_effect=capturing_engine_cls),
        patch("local_ai_brain.main.mlx_whisper", mock_whisper_module),
        patch("local_ai_brain.main.hf_hub_download", return_value="/tmp/mock"),
        patch("local_ai_brain.main.Kokoro", return_value=mock_kokoro_instance),
    ):
        with TestClient(app):
            pass

    assert captured_kwargs.get("model_name") == settings.QWEN_MODEL_PATH
    sc = captured_kwargs.get("scheduler_config")
    assert sc is not None, "scheduler_config was not passed to BatchedEngine"
    assert sc.kv_cache_quantization == settings.LLM_KV_CACHE_QUANTIZATION
    assert sc.kv_cache_quantization_bits == settings.LLM_KV_CACHE_BITS


def test_chat_completions_legacy_model_alias():
    """The old 8-bit model ID should be accepted as an alias for the 4-bit model."""
    from local_ai_brain.config import settings

    with TestClient(app) as client:
        client.app.state.llm_engine = mock_batched_instance
        headers = {"Authorization": "Bearer test-secret-key"}
        legacy_id = "mlx-community/Qwen3.6-35B-A3B-8bit"
        assert legacy_id in settings.QWEN_MODEL_ALIASES
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}], "model": legacy_id},
            headers=headers,
        )
        # Should succeed (not 400) and return the canonical model path
        assert response.status_code == 200
        assert response.json()["model"] == settings.QWEN_MODEL_PATH


def test_audio_speech():
    with TestClient(app) as client:
        client.app.state.tts_model = MockKokoro()
        headers = {"Authorization": "Bearer test-secret-key"}
        response = client.post(
            "/v1/audio/speech",
            json={"input": "hello", "voice": "default", "character": "santa"},
            headers=headers,
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/wav"
        assert len(response.content) > 0

        # Test season routing
        response2 = client.post(
            "/v1/audio/speech",
            json={"input": "hello", "voice": "default", "season": "halloween"},
            headers=headers,
        )
        assert response2.status_code == 200
        assert response2.headers["content-type"] == "audio/wav"


def test_audio_speech_input_too_long():
    from local_ai_brain.config import settings

    with TestClient(app) as client:
        client.app.state.tts_model = MockKokoro()
        headers = {"Authorization": "Bearer test-secret-key"}
        # Exceed limit
        long_input = "a" * (settings.TTS_MAX_CHARACTERS + 1)
        response = client.post(
            "/v1/audio/speech",
            json={"input": long_input, "voice": "default"},
            headers=headers,
        )
        assert response.status_code == 400
        assert "Input text is too long" in response.json()["detail"]


def test_audio_transcription():
    with patch.object(mock_whisper, "transcribe", return_value={"text": "hello"}):
        with TestClient(app) as client:
            client.app.state.stt_model = mock_whisper
            headers = {"Authorization": "Bearer test-secret-key"}
            files = {"file": ("test.wav", b"fake-audio-data", "audio/wav")}
            response = client.post("/v1/audio/transcriptions", files=files, headers=headers)
            assert response.status_code == 200
            assert response.json()["text"] == "hello"


@patch("local_ai_brain.middleware.psutil.virtual_memory")
def test_memory_guard_rejection(mock_vm):
    # Mock psutil to return very high memory usage
    mock_vm_instance = MagicMock()
    # 54.1 GB to exceed 54.0 limit
    mock_vm_instance.used = 54.1 * (1024**3)
    mock_vm.return_value = mock_vm_instance

    with TestClient(app) as client:
        client.app.state.llm_engine = mock_batched_instance
        headers = {"Authorization": "Bearer test-secret-key"}
        # Very large payload to trigger content-length heuristic
        payload = {"messages": [{"role": "user", "content": "a" * 1000000}]}

        response = client.post("/v1/chat/completions", json=payload, headers=headers)
        assert response.status_code == 429
        error_message = response.json()["error"]["message"]
        assert "Memory limit of" in error_message
        assert "exceeded" in error_message


def test_memory_guard_invalid_content_length():
    with TestClient(app) as client:
        client.app.state.llm_engine = mock_batched_instance
        headers = {"Authorization": "Bearer test-secret-key", "Content-Length": "invalid"}
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers=headers,
        )
        assert response.status_code == 200


def test_memory_guard_negative_content_length():
    with TestClient(app) as client:
        client.app.state.llm_engine = mock_batched_instance
        headers = {"Authorization": "Bearer test-secret-key", "Content-Length": "-100"}
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers=headers,
        )
        assert response.status_code == 200


def test_missing_models():
    # Test error handling when models aren't loaded properly
    with TestClient(app) as client:
        client.app.state.llm_engine = None
        client.app.state.stt_model = None
        client.app.state.tts_model = None

        headers = {"Authorization": "Bearer test-secret-key"}

        resp = client.post("/v1/chat/completions", json={"messages": []}, headers=headers)
        assert resp.status_code == 503

        resp = client.post(
            "/v1/audio/speech",
            json={"input": "x", "voice": "x"},
            headers=headers,
        )
        assert resp.status_code == 503

        files = {"file": ("test.wav", b"data", "audio/wav")}
        resp = client.post("/v1/audio/transcriptions", files=files, headers=headers)
        assert resp.status_code == 503


def test_unsupported_model_rejection():
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer test-secret-key"}
        # Chat
        resp = client.post(
            "/v1/chat/completions", json={"model": "llama", "messages": []}, headers=headers
        )
        assert resp.status_code == 400
        # Speech
        resp = client.post(
            "/v1/audio/speech",
            json={"model": "llama", "input": "hi", "voice": "a"},
            headers=headers,
        )
        assert resp.status_code == 400
        # Transcription
        files = {"file": ("test.wav", b"data", "audio/wav")}
        resp = client.post(
            "/v1/audio/transcriptions", data={"model": "llama"}, files=files, headers=headers
        )
        assert resp.status_code == 400


def test_audio_transcription_with_language():
    with patch.object(mock_whisper, "transcribe", return_value={"text": "hello"}):
        with TestClient(app) as client:
            client.app.state.stt_model = mock_whisper
            headers = {"Authorization": "Bearer test-secret-key"}
            files = {"file": ("test.wav", b"fake-audio-data", "audio/wav")}
            response = client.post(
                "/v1/audio/transcriptions", data={"language": "en"}, files=files, headers=headers
            )
            assert response.status_code == 200
            assert response.json()["text"] == "hello"


def test_audio_transcription_error_path():
    with patch.object(mock_whisper, "transcribe", side_effect=Exception("Whisper error")):
        with TestClient(app) as client:
            client.app.state.stt_model = mock_whisper
            headers = {"Authorization": "Bearer test-secret-key"}
            files = {"file": ("test.wav", b"fake-audio-data", "audio/wav")}
            response = client.post("/v1/audio/transcriptions", files=files, headers=headers)
            assert response.status_code == 500


def test_audio_speech_precedence():
    with TestClient(app) as client:
        client.app.state.tts_model = MockKokoro()
        headers = {"Authorization": "Bearer test-secret-key"}
        # Both character and season provided to trigger precedence log
        response = client.post(
            "/v1/audio/speech",
            json={"input": "hello", "voice": "default", "character": "santa", "season": "winter"},
            headers=headers,
        )
        assert response.status_code == 200


def test_chat_completions_list_content():
    with TestClient(app) as client:
        client.app.state.llm_engine = mock_batched_instance
        headers = {"Authorization": "Bearer test-secret-key"}
        response = client.post(
            "/v1/chat/completions",
            json={
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "hi"},
                            {"type": "text", "text": " and more"},
                        ],
                    }
                ]
            },
            headers=headers,
        )
        assert response.status_code == 200


def test_list_models():
    from fastapi.testclient import TestClient

    from local_ai_brain.config import settings
    from local_ai_brain.main import app

    with TestClient(app) as client:
        response = client.get("/v1/models", headers={"Authorization": "Bearer test-secret-key"})
        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "list"
        ids = [m["id"] for m in data["data"]]
        assert settings.QWEN_MODEL_PATH in ids
        assert settings.WHISPER_MODEL_PATH in ids
        assert settings.KOKORO_MODEL_PATH in ids

        qwen_model = next(m for m in data["data"] if m["id"] == settings.QWEN_MODEL_PATH)
        assert qwen_model["max_model_len"] == settings.MAX_CONTEXT_TOKENS
        assert qwen_model["context_window"] == settings.MAX_CONTEXT_TOKENS
        assert qwen_model["max_position_embeddings"] == settings.MAX_CONTEXT_TOKENS


def test_get_model():
    from fastapi.testclient import TestClient

    from local_ai_brain.config import settings
    from local_ai_brain.main import app

    with TestClient(app) as client:
        response = client.get(
            f"/v1/models/{settings.QWEN_MODEL_PATH}",
            headers={"Authorization": "Bearer test-secret-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == settings.QWEN_MODEL_PATH
        assert data["object"] == "model"
        assert data["max_model_len"] == settings.MAX_CONTEXT_TOKENS
        assert data["context_window"] == settings.MAX_CONTEXT_TOKENS
        assert data["max_position_embeddings"] == settings.MAX_CONTEXT_TOKENS


def test_get_model_not_found():
    from fastapi.testclient import TestClient

    from local_ai_brain.main import app

    with TestClient(app) as client:
        response = client.get(
            "/v1/models/non-existent-model", headers={"Authorization": "Bearer test-secret-key"}
        )
        assert response.status_code == 404


def test_models_unauthorized():
    from fastapi.testclient import TestClient

    from local_ai_brain.main import app

    with TestClient(app) as client:
        # No header
        response = client.get("/v1/models")
        assert response.status_code == 401

        # Bad key
        response = client.get("/v1/models", headers={"Authorization": "Bearer bad-key"})
        assert response.status_code == 401
