import os
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


def _load_app():
    os.environ.setdefault("LOCAL_API_KEY", "test-secret-key")
    from local_ai_brain.main import app

    return app


app = _load_app()
def test_health():
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


def test_metrics():
    with TestClient(app) as client:
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "http_requests_total" in response.text


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


def test_audio_speech():
    with TestClient(app) as client:
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


def test_audio_transcription():
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer test-secret-key"}
        files = {"file": ("test.wav", b"fake-audio-data", "audio/wav")}
        response = client.post("/v1/audio/transcriptions", files=files, headers=headers)
        assert response.status_code == 200
        assert "text" in response.json()


@patch("local_ai_brain.middleware.psutil.virtual_memory")
def test_memory_guard_rejection(mock_vm):
    # Mock psutil to return very high memory usage
    mock_vm_instance = MagicMock()
    # 48.1 GB to exceed 48.0 limit
    mock_vm_instance.used = 48.1 * (1024**3)
    mock_vm.return_value = mock_vm_instance

    with TestClient(app) as client:
        headers = {"Authorization": "Bearer test-secret-key"}
        # Very large payload to trigger content-length heuristic
        payload = {"messages": [{"role": "user", "content": "a" * 1000000}]}

        response = client.post("/v1/chat/completions", json=payload, headers=headers)
        assert response.status_code == 429
        assert "Memory limit of 48.0GB exceeded" in response.json()["error"]["message"]


def test_missing_models():
    # Test error handling when models aren't loaded properly
    with TestClient(app) as client:
        # Clear out state manually to simulate failure
        app.state.llm_engine = None
        app.state.stt_model = None
        app.state.tts_model = None

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
