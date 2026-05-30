import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

# Set testing environment variables before importing app
os.environ["TESTING"] = "1"
os.environ["LOCAL_API_KEY"] = "test-api-key"

from local_ai_brain.config import settings
from local_ai_brain.main import app


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client


@pytest.fixture
def qwen_alias():
    assert settings.QWEN_MODEL_ALIASES
    return settings.QWEN_MODEL_ALIASES[0]


def test_health_check(client):
    response = client.get("/health", headers={"Authorization": "Bearer test-api-key"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "proxy": "active"}


def test_unauthorized(client):
    response = client.get("/health")
    assert response.status_code == 401

    response = client.get("/health", headers={"Authorization": "Bearer wrong-key"})
    assert response.status_code == 401


@patch("httpx.AsyncClient.get", new_callable=AsyncMock)
def test_list_models(mock_get, client):
    # Mock the vLLM response
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "object": "list",
        "data": [
            {
                "id": "Qwen/Qwen2.5-14B-Instruct-1M",
                "object": "model",
                "created": 1234567890,
                "owned_by": "vllm",
            }
        ],
    }
    mock_get.return_value = mock_response

    response = client.get("/v1/models", headers={"Authorization": "Bearer test-api-key"})
    assert response.status_code == 200
    data = response.json()
    assert data["object"] == "list"
    ids = [m["id"] for m in data["data"]]

    # Assert vLLM model is present
    assert "Qwen/Qwen2.5-14B-Instruct-1M" in ids
    # Assert injected models are present
    assert settings.WHISPER_MODEL_PATH in ids
    assert settings.KOKORO_MODEL_PATH in ids


@patch("httpx.AsyncClient.get", new_callable=AsyncMock)
def test_list_models_vllm_failure(mock_get, client):
    # If vLLM is down or fails, we should still return the local audio models
    mock_get.side_effect = Exception("vLLM connection refused")

    response = client.get("/v1/models", headers={"Authorization": "Bearer test-api-key"})
    assert response.status_code == 200
    data = response.json()
    assert data["object"] == "list"
    ids = [m["id"] for m in data["data"]]

    assert settings.WHISPER_MODEL_PATH in ids
    assert settings.KOKORO_MODEL_PATH in ids


@patch("httpx.AsyncClient.get", new_callable=AsyncMock)
def test_get_model_vllm(mock_get, client):
    # Mock the vLLM response
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "object": "list",
        "data": [
            {
                "id": "some-vllm-model",
                "object": "model",
                "created": 1234567890,
                "owned_by": "vllm",
            }
        ],
    }
    mock_get.return_value = mock_response

    response = client.get(
        "/v1/models/some-vllm-model", headers={"Authorization": "Bearer test-api-key"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "some-vllm-model"


@patch("httpx.AsyncClient.get", new_callable=AsyncMock)
def test_get_model_local(mock_get, client):
    # For local audio models, it should intercept and return locally without calling backend
    response = client.get(
        f"/v1/models/{settings.WHISPER_MODEL_PATH}",
        headers={"Authorization": "Bearer test-api-key"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == settings.WHISPER_MODEL_PATH
    assert data["owned_by"] == "local-ai-brain"
    mock_get.assert_not_called()


@patch("httpx.AsyncClient.get", new_callable=AsyncMock)
def test_get_model_alias_normalization(mock_get, client):
    # Mock the vLLM response containing the canonical model
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "object": "list",
        "data": [
            {
                "id": settings.QWEN_MODEL_PATH,
                "object": "model",
                "aliases": settings.QWEN_MODEL_ALIASES,
            }
        ],
    }
    mock_get.return_value = mock_response

    # Test that model aliases are normalized to the canonical path
    alias = settings.QWEN_MODEL_ALIASES[0]
    response = client.get(
        f"/v1/models/{alias}",
        headers={"Authorization": "Bearer test-api-key"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == settings.QWEN_MODEL_PATH


@patch("httpx.AsyncClient.get", new_callable=AsyncMock)
def test_metrics_aggregation(mock_get, client):
    # Mock responses for vLLM, STT, and TTS
    def side_effect(url, **kwargs):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        if "8001" in url:
            mock_resp.content = b"vllm_metric 1.0"
        elif "8002" in url:
            mock_resp.content = b"stt_metric 2.0"
        elif "8003" in url:
            mock_resp.content = b"tts_metric 3.0"
        return mock_resp

    mock_get.side_effect = side_effect

    response = client.get("/metrics", headers={"Authorization": "Bearer test-api-key"})
    assert response.status_code == 200

    content = response.content
    assert b"vllm_metric 1.0" in content
    assert b"stt_metric 2.0" in content
    assert b"tts_metric 3.0" in content
    # Proxy metric should also be present (from MetricsMiddleware)
    assert b"http_requests_total" in content


@patch("httpx.AsyncClient.send", new_callable=AsyncMock)
def test_proxy_stt(mock_send, client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {}
    mock_response.aclose = AsyncMock()

    async def async_iter():
        yield b'{"text": "hello"}'

    mock_response.aiter_bytes = async_iter
    mock_send.return_value = mock_response

    response = client.post(
        "/v1/audio/transcriptions", headers={"Authorization": "Bearer test-api-key"}
    )
    assert response.status_code == 200
    assert response.json() == {"text": "hello"}

    # Assert it called STT_URL
    req = mock_send.call_args[0][0]
    assert "8002" in str(req.url)


@patch("httpx.AsyncClient.send", new_callable=AsyncMock)
def test_proxy_tts(mock_send, client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {}
    mock_response.aclose = AsyncMock()

    async def async_iter():
        yield b"audio_data"

    mock_response.aiter_bytes = async_iter
    mock_send.return_value = mock_response

    response = client.post("/v1/audio/speech", headers={"Authorization": "Bearer test-api-key"})
    assert response.status_code == 200
    assert response.content == b"audio_data"

    req = mock_send.call_args[0][0]
    assert "8003" in str(req.url)


@patch("httpx.AsyncClient.send", new_callable=AsyncMock)
def test_proxy_chat(mock_send, client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {}
    mock_response.aclose = AsyncMock()

    async def async_iter():
        yield b'{"id": "chat-1"}'

    mock_response.aiter_bytes = async_iter
    mock_send.return_value = mock_response

    response = client.post("/v1/chat/completions", headers={"Authorization": "Bearer test-api-key"})
    assert response.status_code == 200

    req = mock_send.call_args[0][0]
    assert "8001" in str(req.url)


@patch("httpx.AsyncClient.send", new_callable=AsyncMock)
def test_proxy_chat_alias_model_normalization(mock_send, client, qwen_alias):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {}
    mock_response.aclose = AsyncMock()

    async def async_iter():
        yield b'{"id": "chat-1"}'

    mock_response.aiter_bytes = async_iter
    mock_send.return_value = mock_response

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-api-key"},
        json={
            "model": qwen_alias,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert response.status_code == 200

    req = mock_send.call_args[0][0]
    assert req.content
    payload = json.loads(req.content.decode("utf-8"))
    assert payload["model"] == settings.QWEN_MODEL_PATH


@patch("httpx.AsyncClient.send", new_callable=AsyncMock)
def test_proxy_completions_alias_model_normalization(mock_send, client, qwen_alias):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {}
    mock_response.aclose = AsyncMock()

    async def async_iter():
        yield b'{"id": "cmpl-1"}'

    mock_response.aiter_bytes = async_iter
    mock_send.return_value = mock_response

    response = client.post(
        "/v1/completions",
        headers={"Authorization": "Bearer test-api-key"},
        json={"model": qwen_alias, "prompt": "hello"},
    )
    assert response.status_code == 200

    req = mock_send.call_args[0][0]
    assert req.content
    payload = json.loads(req.content.decode("utf-8"))
    assert payload["model"] == settings.QWEN_MODEL_PATH


@patch("httpx.AsyncClient.send", new_callable=AsyncMock)
def test_proxy_bad_gateway(mock_send, client):
    mock_send.side_effect = httpx.RequestError("Connection refused")

    response = client.post("/v1/chat/completions", headers={"Authorization": "Bearer test-api-key"})
    assert response.status_code == 502
    assert response.json() == {"detail": "Bad Gateway"}


@patch("httpx.AsyncClient.send", new_callable=AsyncMock)
def test_proxy_chat_default_max_tokens(mock_send, client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = httpx.Headers({"Content-Type": "application/json"})

    async def mock_aiter_bytes():
        yield b'{"id":"chatcmpl-123"}'

    mock_response.aiter_bytes = mock_aiter_bytes

    async def mock_aclose():
        pass

    mock_response.aclose = mock_aclose
    mock_send.return_value = mock_response

    payload = {
        "model": "mlx-community/Qwen3.6-35B-A3B-4bit",
        "messages": [{"role": "user", "content": "Hello"}],
        # max_tokens not provided
    }
    response = client.post(
        "/v1/chat/completions",
        json=payload,
        headers={"Authorization": f"Bearer {settings.LOCAL_API_KEY}"},
    )
    assert response.status_code == 200

    req = mock_send.call_args[0][0]
    assert req.content
    sent_payload = json.loads(req.content.decode("utf-8"))
    assert sent_payload["max_tokens"] == settings.DEFAULT_MAX_TOKENS


@patch("httpx.AsyncClient.send", new_callable=AsyncMock)
def test_proxy_chat_max_tokens_clamping(mock_send, client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = httpx.Headers({"Content-Type": "application/json"})

    async def mock_aiter_bytes():
        yield b'{"id":"chatcmpl-123"}'

    mock_response.aiter_bytes = mock_aiter_bytes

    async def mock_aclose():
        pass

    mock_response.aclose = mock_aclose
    mock_send.return_value = mock_response

    payload = {
        "model": "mlx-community/Qwen3.6-35B-A3B-4bit",
        "messages": [{"role": "user", "content": "Hello"}],
        "max_tokens": 1000000,  # Larger than MAX_CONTEXT_TOKENS
    }
    response = client.post(
        "/v1/chat/completions",
        json=payload,
        headers={"Authorization": f"Bearer {settings.LOCAL_API_KEY}"},
    )
    assert response.status_code == 200

    req = mock_send.call_args[0][0]
    assert req.content
    sent_payload = json.loads(req.content.decode("utf-8"))
    assert sent_payload["max_tokens"] == settings.MAX_CONTEXT_TOKENS


@patch("httpx.AsyncClient.send", new_callable=AsyncMock)
def test_proxy_completions_max_tokens_clamping(mock_send, client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = httpx.Headers({"Content-Type": "application/json"})

    async def mock_aiter_bytes():
        yield b'{"id":"cmpl-123"}'

    mock_response.aiter_bytes = mock_aiter_bytes

    async def mock_aclose():
        pass

    mock_response.aclose = mock_aclose
    mock_send.return_value = mock_response

    payload = {
        "model": "mlx-community/Qwen3.6-35B-A3B-4bit",
        "prompt": "Hello",
        "max_tokens": 1000000,  # Larger than MAX_CONTEXT_TOKENS
    }
    response = client.post(
        "/v1/completions",
        json=payload,
        headers={"Authorization": f"Bearer {settings.LOCAL_API_KEY}"},
    )
    assert response.status_code == 200

    req = mock_send.call_args[0][0]
    assert req.content
    sent_payload = json.loads(req.content.decode("utf-8"))
    assert sent_payload["max_tokens"] == settings.MAX_CONTEXT_TOKENS


def test_normalize_model_metadata():
    from local_ai_brain.main import normalize_model_metadata

    # Test with meta and n_ctx
    model = {
        "id": "test-model",
        "meta": {"n_ctx": 1024, "n_ctx_train": 2048, "other": "value"},
    }
    normalized = normalize_model_metadata(model)
    assert normalized["max_model_len"] == 1024
    assert normalized["context_window"] == 1024
    assert normalized["max_position_embeddings"] == 1024
    assert "n_ctx_train" not in normalized["meta"]
    assert normalized["meta"]["other"] == "value"

    # Test without meta
    model = {"id": "test-model"}
    normalized = normalize_model_metadata(model)
    assert normalized == {"id": "test-model"}

    # Test with meta but no n_ctx
    model = {"id": "test-model", "meta": {"other": "value"}}
    normalized = normalize_model_metadata(model)
    assert "max_model_len" not in normalized
    assert normalized["meta"]["other"] == "value"


@patch("httpx.AsyncClient.send", new_callable=AsyncMock)
@patch("local_ai_brain.main.time.perf_counter")
def test_stream_generator_usage_extraction_sse(mock_perf, mock_send, client):
    # Setup mocks for timing
    # We need enough values for all calls to perf_counter
    # 1. Body read (potential)
    # 2. request_start = 100.0
    # 3. first_token_time = 100.5
    # 4. request_end = 101.5
    mock_perf.side_effect = [99.0, 100.0, 100.5, 101.5, 101.5, 101.5, 101.5]

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = httpx.Headers({"Content-Type": "text/event-stream"})
    mock_response.aclose = AsyncMock()

    async def mock_aiter_bytes():
        # SSE format usage chunk
        yield b'data: {"choices": [{"delta": {"content": "hello"}}]}\n\n'
        yield b'data: {"usage": {"prompt_tokens": 10, "completion_tokens": 20}}\n\n'
        yield b"data: [DONE]\n\n"

    mock_response.aiter_bytes = mock_aiter_bytes
    mock_send.return_value = mock_response

    # Use a logger patch to verify output
    with patch("local_ai_brain.main.logger.info") as mock_logger:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
            headers={"Authorization": f"Bearer {settings.LOCAL_API_KEY}"},
        )
        assert response.status_code == 200
        # Consume the stream to trigger the finally block
        for _ in response.iter_lines():
            pass

        # Verify logger was called with TPS info
        # request_start=100.0, first_token=100.5 => prefill=0.5s
        # prompt_tokens=10 => 20.00 t/s
        # request_end=101.5 => generation=1.0s
        # completion_tokens=20 => 20.00 t/s
        mock_logger.assert_called()
        call_args = mock_logger.call_args[0]
        assert "{} {} completed: {} in ({}) | {} out ({}) | {:.2f}s total" == call_args[0]
        assert "[LLM]" == call_args[1]
        assert "test-model" == call_args[2]
        assert 10 == call_args[3]
        assert "20.00 t/s" == call_args[4]
        assert 20 == call_args[5]
        assert "20.00 t/s" == call_args[6]
        # total = 101.5 - 100.0 = 1.5s
        assert 1.50 == pytest.approx(call_args[7], abs=0.01)


@patch("httpx.AsyncClient.send", new_callable=AsyncMock)
@patch("local_ai_brain.main.time.perf_counter")
def test_stream_generator_usage_extraction_raw_json(mock_perf, mock_send, client):
    # Setup mocks for timing
    # 1. Body read (potential)
    # 2. request_start = 100.0
    # 3. first_token_time = 100.1
    # 4. request_end = 100.5
    mock_perf.side_effect = [99.0, 100.0, 100.1, 100.5, 100.5, 100.5, 100.5]

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = httpx.Headers({"Content-Type": "application/json"})
    mock_response.aclose = AsyncMock()

    async def mock_aiter_bytes():
        # Raw JSON format usage
        yield b'{"usage": {"prompt_tokens": 5, "completion_tokens": 10}}'

    mock_response.aiter_bytes = mock_aiter_bytes
    mock_send.return_value = mock_response

    with patch("local_ai_brain.main.logger.info") as mock_logger:
        response = client.post(
            "/v1/chat/completions",
            json={"model": "test-model", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": f"Bearer {settings.LOCAL_API_KEY}"},
        )
        assert response.status_code == 200
        # Consume the stream
        for _ in response.iter_lines():
            pass

        mock_logger.assert_called()
        call_args = mock_logger.call_args[0]
        # request_start=100.0, first_token=100.1 => prefill=0.1s
        # prompt_tokens=5 => 50.00 t/s
        # request_end=100.5 => generation=0.4s
        # completion_tokens=10 => 25.00 t/s
        assert "{} {} completed: {} in ({}) | {} out ({}) | {:.2f}s total" == call_args[0]
        assert "[LLM]" == call_args[1]
        assert "test-model" == call_args[2]
        assert 5 == call_args[3]
        assert "50.00 t/s" == call_args[4]
        assert 10 == call_args[5]
        assert "25.00 t/s" == call_args[6]
        assert 0.50 == pytest.approx(call_args[7], abs=0.01)


@patch("httpx.AsyncClient.send", new_callable=AsyncMock)
@patch("local_ai_brain.main.time.perf_counter")
def test_stream_generator_no_usage(mock_perf, mock_send, client):
    mock_perf.side_effect = [100.0, 100.1, 100.5, 100.5, 100.5, 100.5]

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = httpx.Headers({"Content-Type": "application/json"})
    mock_response.aclose = AsyncMock()

    async def mock_aiter_bytes():
        yield b'{"id": "no-usage"}'

    mock_response.aiter_bytes = mock_aiter_bytes
    mock_send.return_value = mock_response

    with patch("local_ai_brain.main.logger.info") as mock_logger:
        response = client.post(
            "/v1/chat/completions",
            json={"model": "test-model", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": f"Bearer {settings.LOCAL_API_KEY}"},
        )
        assert response.status_code == 200
        for _ in response.iter_lines():
            pass

        mock_logger.assert_called()
        log_msg = mock_logger.call_args[0][0]
        assert "(No usage found)" in log_msg


@patch("httpx.AsyncClient.send", new_callable=AsyncMock)
@patch("local_ai_brain.main.time.perf_counter")
def test_stream_generator_fast_tps(mock_perf, mock_send, client):
    # Test "FAST" and "N/A" cases
    # 1. Body read (potential)
    # 2. request_start = 100.0
    # 3. first_token_time = 100.0001 (too fast)
    # 4. request_end = 100.005 (too fast for generation)
    mock_perf.side_effect = [99.0, 100.0, 100.0001, 100.005, 100.005, 100.005, 100.005]

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = httpx.Headers({"Content-Type": "application/json"})
    mock_response.aclose = AsyncMock()

    async def mock_aiter_bytes():
        yield b'{"usage": {"prompt_tokens": 5, "completion_tokens": 10}}'

    mock_response.aiter_bytes = mock_aiter_bytes
    mock_send.return_value = mock_response

    with patch("local_ai_brain.main.logger.info") as mock_logger:
        response = client.post(
            "/v1/chat/completions",
            json={"model": "test-model", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": f"Bearer {settings.LOCAL_API_KEY}"},
        )
        assert response.status_code == 200
        for _ in response.iter_lines():
            pass

        mock_logger.assert_called()
        call_args = mock_logger.call_args[0]
        assert "{} {} completed: {} in ({}) | {} out ({}) | {:.2f}s total" == call_args[0]
        assert "[LLM]" == call_args[1]
        assert "FAST" == call_args[4]
        assert 10 == call_args[5]
        assert "FAST" == call_args[6]


@patch("httpx.AsyncClient.send", new_callable=AsyncMock)
def test_proxy_invalid_json_payload(mock_send, client):
    # Tests line 66 in main.py
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {}
    mock_response.aclose = AsyncMock()

    async def async_iter():
        yield b"ok"

    mock_response.aiter_bytes = async_iter
    mock_send.return_value = mock_response

    # Send invalid JSON with application/json header
    response = client.post(
        "/v1/chat/completions",
        content="invalid-json",
        headers={
            "Authorization": f"Bearer {settings.LOCAL_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 200


@patch("httpx.AsyncClient.send", new_callable=AsyncMock)
def test_proxy_stream_content(mock_send, client):
    # Tests line 114 in main.py (non-should_normalize_model path)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {}
    mock_response.aclose = AsyncMock()

    async def async_iter():
        yield b"ok"

    mock_response.aiter_bytes = async_iter
    mock_send.return_value = mock_response

    # Use a path that doesn't trigger should_normalize_model (e.g. not /v1/chat or /v1/completions)
    response = client.post(
        "/v1/audio/transcriptions",
        content=b"some-audio-data",
        headers={"Authorization": f"Bearer {settings.LOCAL_API_KEY}", "Content-Type": "audio/wav"},
    )
    assert response.status_code == 200


@patch("httpx.AsyncClient.get", new_callable=AsyncMock)
def test_metrics_failure_logging(mock_get, client):
    # Tests lines 482-483 in main.py
    def side_effect(url, **kwargs):
        if "metrics" in url:
            if "8001" in url:  # vLLM
                raise httpx.ConnectError("Connection failed")
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b"metric 1.0"
            return mock_resp
        return MagicMock()

    mock_get.side_effect = side_effect

    with patch("local_ai_brain.main.logger.warning") as mock_warn:
        response = client.get(
            "/metrics", headers={"Authorization": f"Bearer {settings.LOCAL_API_KEY}"}
        )
        assert response.status_code == 200
        mock_warn.assert_called()
        assert "Failed to fetch metrics from vLLM" in mock_warn.call_args[0][0]


@patch("httpx.AsyncClient.send", new_callable=AsyncMock)
def test_proxy_request_stream_options_edge_cases(mock_send, client):
    # Tests lines 89-91 in main.py
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {}
    mock_response.aclose = AsyncMock()

    async def async_iter():
        yield b"ok"

    mock_response.aiter_bytes = async_iter
    mock_send.return_value = mock_response

    # Case: stream_options is not a dict
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "test-model",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
            "stream_options": None,
        },
        headers={"Authorization": f"Bearer {settings.LOCAL_API_KEY}"},
    )
    assert response.status_code == 200
    sent_payload = json.loads(mock_send.call_args[0][0].content.decode("utf-8"))
    assert sent_payload["stream_options"] == {"include_usage": True}


@patch("httpx.AsyncClient.send", new_callable=AsyncMock)
def test_proxy_chat_logging(mock_send, client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {}
    mock_response.aclose = AsyncMock()

    async def async_iter():
        yield b'{"id": "chat-1"}'

    mock_response.aiter_bytes = async_iter
    mock_send.return_value = mock_response

    with patch("local_ai_brain.main.logger") as mock_logger:
        response = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer test-api-key"},
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Tell me a story about a brain."}],
            },
        )
        assert response.status_code == 200

        # Check that logger.info was called with the chat preview
        log_messages = [call.args[0] for call in mock_logger.info.call_args_list]
        assert any("Incoming chat from" in msg for msg in log_messages)
        assert any("Tell me a story about a brain." in msg for msg in log_messages)
