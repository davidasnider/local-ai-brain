import os
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

# Set environment variables BEFORE any imports from the app
os.environ["TESTING"] = "1"
os.environ["LOCAL_API_KEY"] = "test-secret-key"  # pragma: allowlist secret

from local_ai_brain.models.stt_server import app


def test_stt_auth_failure():
    with TestClient(app) as client:
        # Missing API Key
        response = client.post("/v1/audio/transcriptions")
        assert response.status_code == 401

        # Invalid API Key
        response = client.post(
            "/v1/audio/transcriptions", headers={"Authorization": "Bearer invalid-key"}
        )
        assert response.status_code == 401


def test_stt_unsupported_model():
    with TestClient(app) as client:
        # Provide a dummy file
        files = {"file": ("test.wav", b"dummy content", "audio/wav")}
        data = {"model": "invalid-model"}

        response = client.post(
            "/v1/audio/transcriptions",
            headers={"Authorization": "Bearer test-secret-key"},
            files=files,
            data=data,
        )
        assert response.status_code == 400
        assert "Unsupported model" in response.json()["detail"]


@patch("local_ai_brain.models.stt_server.stt_model")
@patch("soundfile.info")
def test_stt_happy_path(mock_sf_info, mock_stt_model):
    from local_ai_brain.config import settings

    # Mock soundfile info for duration
    mock_info = MagicMock()
    mock_info.samplerate = 16000
    mock_info.frames = 16000 * 5  # 5 seconds
    mock_sf_info.return_value = mock_info

    # Mock whisper result
    mock_stt_model.transcribe.return_value = {"text": "Hello world"}

    with TestClient(app) as client:
        files = {"file": ("test.wav", b"dummy content", "audio/wav")}

        response = client.post(
            "/v1/audio/transcriptions",
            headers={"Authorization": "Bearer test-secret-key"},
            files=files,
        )

        assert response.status_code == 200
        assert response.json() == {"text": "Hello world"}

        # Verify whisper was called correctly
        mock_stt_model.transcribe.assert_called_once()
        args, kwargs = mock_stt_model.transcribe.call_args
        assert kwargs["path_or_hf_repo"] == settings.WHISPER_MODEL_PATH


def test_stt_health():
    with TestClient(app) as client:
        response = client.get("/health", headers={"Authorization": "Bearer test-secret-key"})
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


def test_stt_metrics():
    with TestClient(app) as client:
        response = client.get("/metrics", headers={"Authorization": "Bearer test-secret-key"})
        assert response.status_code == 200


@patch("local_ai_brain.models.stt_server.stt_model")
@patch("soundfile.info")
def test_stt_language_form(mock_sf_info, mock_stt_model):
    # Mock soundfile info
    mock_info = MagicMock()
    mock_info.samplerate = 16000
    mock_info.frames = 16000
    mock_sf_info.return_value = mock_info

    mock_stt_model.transcribe.return_value = {"text": "Bonjour"}

    with TestClient(app) as client:
        files = {"file": ("test.wav", b"dummy content", "audio/wav")}
        data = {"language": "fr"}
        response = client.post(
            "/v1/audio/transcriptions",
            headers={"Authorization": "Bearer test-secret-key"},
            files=files,
            data=data,
        )
        assert response.status_code == 200
        assert response.json()["text"] == "Bonjour"
        mock_stt_model.transcribe.assert_called_once()
        assert mock_stt_model.transcribe.call_args[1]["language"] == "fr"


@patch("local_ai_brain.models.stt_server.stt_model")
def test_stt_transcription_failure(mock_stt_model):
    mock_stt_model.transcribe.side_effect = Exception("Whisper error")

    with TestClient(app) as client:
        files = {"file": ("test.wav", b"dummy content", "audio/wav")}
        response = client.post(
            "/v1/audio/transcriptions",
            headers={"Authorization": "Bearer test-secret-key"},
            files=files,
        )
        assert response.status_code == 500
        assert "Transcription failed" in response.json()["detail"]
