import os
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

# Set environment variables BEFORE any imports from the app
os.environ["TESTING"] = "1"
os.environ["LOCAL_API_KEY"] = "test-secret-key"  # pragma: allowlist secret

from local_ai_brain.models.tts_server import app


def test_tts_auth_failure():
    with TestClient(app) as client:
        # Missing API Key
        response = client.post("/v1/audio/speech", json={"input": "test", "voice": "af_heart"})
        assert response.status_code == 401

        # Invalid API Key
        response = client.post(
            "/v1/audio/speech",
            headers={"Authorization": "Bearer invalid-key"},
            json={"input": "test", "voice": "af_heart"},
        )
        assert response.status_code == 401


def test_tts_unsupported_model_or_format():
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer test-secret-key"}

        # Unsupported model
        response = client.post(
            "/v1/audio/speech",
            headers=headers,
            json={"input": "test", "model": "invalid-model", "voice": "af_heart"},
        )
        assert response.status_code == 400
        assert "Unsupported model" in response.json()["detail"]

        # Unsupported format
        response = client.post(
            "/v1/audio/speech",
            headers=headers,
            json={"input": "test", "response_format": "mp3", "voice": "af_heart"},
        )
        assert response.status_code == 400
        assert "Unsupported response_format" in response.json()["detail"]


def test_tts_input_length_enforcement():
    from local_ai_brain.config import settings

    with TestClient(app) as client:
        headers = {"Authorization": "Bearer test-secret-key"}

        # Text exceeding limit
        long_text = "a" * (settings.TTS_MAX_CHARACTERS + 1)
        response = client.post(
            "/v1/audio/speech", headers=headers, json={"input": long_text, "voice": "af_heart"}
        )
        assert response.status_code == 400
        assert "Input text is too long" in response.json()["detail"]


@patch("local_ai_brain.models.tts_server.tts_model")
@patch("soundfile.write")
def test_tts_happy_path(mock_sf_write, mock_tts_model):
    # Mock kokoro result
    mock_tts_model.create.return_value = (MagicMock(), 24000)

    with TestClient(app) as client:
        headers = {"Authorization": "Bearer test-secret-key"}
        payload = {"input": "Hello world", "voice": "af_heart", "speed": 1.2}

        response = client.post("/v1/audio/speech", headers=headers, json=payload)

        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/wav"

        # Verify kokoro was called correctly
        mock_tts_model.create.assert_called_once()
        args, kwargs = mock_tts_model.create.call_args
        assert args[0] == "Hello world"
        assert kwargs["voice"] == "af_heart"
        assert kwargs["speed"] == 1.2


def test_tts_health():
    with TestClient(app) as client:
        response = client.get("/health", headers={"Authorization": "Bearer test-secret-key"})
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


def test_tts_metrics():
    with TestClient(app) as client:
        response = client.get("/metrics", headers={"Authorization": "Bearer test-secret-key"})
        assert response.status_code == 200


@patch("local_ai_brain.models.tts_server.tts_model")
@patch("soundfile.write")
def test_tts_dynamic_routing(mock_sf_write, mock_tts_model):
    mock_tts_model.create.return_value = (MagicMock(), 24000)

    with TestClient(app) as client:
        headers = {"Authorization": "Bearer test-secret-key"}

        # Test character routing
        client.post(
            "/v1/audio/speech",
            headers=headers,
            json={"input": "test", "character": "santa", "voice": "v1"},
        )
        assert mock_tts_model.create.call_args[1]["voice"] == "character_santa"

        # Test season routing (takes precedence)
        client.post(
            "/v1/audio/speech",
            headers=headers,
            json={"input": "test", "character": "santa", "season": "winter", "voice": "v1"},
        )
        assert mock_tts_model.create.call_args[1]["voice"] == "season_winter"


@patch("local_ai_brain.models.tts_server.tts_model")
def test_tts_generation_failure(mock_tts_model):
    mock_tts_model.create.side_effect = Exception("Kokoro error")

    with TestClient(app) as client:
        response = client.post(
            "/v1/audio/speech",
            headers={"Authorization": "Bearer test-secret-key"},
            json={"input": "test", "voice": "af_heart"},
        )
        assert response.status_code == 500
        assert "TTS generation failed" in response.json()["detail"]
