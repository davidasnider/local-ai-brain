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


@patch("local_ai_brain.main.proxy_request", new_callable=AsyncMock)
def test_get_model_vllm(mock_proxy_request, client):
    # For a random model, it should proxy to vLLM
    mock_proxy_response = MagicMock()
    mock_proxy_response.status_code = 200
    mock_proxy_request.return_value = mock_proxy_response

    response = client.get(
        "/v1/models/some-vllm-model", headers={"Authorization": "Bearer test-api-key"}
    )
    assert response.status_code == 200
    mock_proxy_request.assert_called_once()


def test_get_model_local(client):
    # For local audio models, it should intercept and return locally
    response = client.get(
        f"/v1/models/{settings.WHISPER_MODEL_PATH}",
        headers={"Authorization": "Bearer test-api-key"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == settings.WHISPER_MODEL_PATH
    assert data["owned_by"] == "local-ai-brain"


def test_get_model_alias_normalization(client):
    # Test that model aliases are normalized to the canonical path
    alias = settings.QWEN_MODEL_ALIASES[0]
    response = client.get(
        f"/v1/models/{alias}",
        headers={"Authorization": "Bearer test-api-key"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == settings.QWEN_MODEL_PATH
    assert data["type"] == "llm"


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
def test_proxy_bad_gateway(mock_send, client):
    mock_send.side_effect = httpx.RequestError("Connection refused")

    response = client.post("/v1/chat/completions", headers={"Authorization": "Bearer test-api-key"})
    assert response.status_code == 502
    assert response.json() == {"detail": "Bad Gateway"}
