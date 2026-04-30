"""Tests for the local-brain interactive CLI."""

import json
import os
import sys
from unittest.mock import MagicMock, mock_open, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers to import the CLI module with controlled environment variables
# ---------------------------------------------------------------------------
def _import_cli(base_url="http://localhost:8000/v1", api_key="test-key"):
    """Re-import cli module with specified env vars."""
    # Remove cached module so module-level constants are re-evaluated
    if "local_ai_brain.cli" in sys.modules:
        del sys.modules["local_ai_brain.cli"]
    with patch.dict(os.environ, {"OPENAI_API_BASE": base_url, "LOCAL_API_KEY": api_key}):
        import local_ai_brain.cli as cli_module  # noqa: E402

        return cli_module


@pytest.fixture()
def cli():
    return _import_cli()


# ---------------------------------------------------------------------------
# _request_json
# ---------------------------------------------------------------------------
class TestRequestJson:
    def test_success(self, cli):
        response_data = {"choices": [{"message": {"content": "Hello!"}}]}
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps(response_data).encode()

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = cli._request_json("/chat/completions", {"messages": []})

        assert result == response_data

    def test_url_construction(self, cli):
        """Trailing slash on BASE_URL is stripped correctly."""
        captured = {}

        def fake_urlopen(req):
            captured["url"] = req.full_url
            mock_resp = MagicMock()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_resp.read.return_value = b"{}"
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            cli._request_json("/chat/completions", {})

        assert captured["url"] == "http://localhost:8000/v1/chat/completions"


# ---------------------------------------------------------------------------
# _request_multipart
# ---------------------------------------------------------------------------
class TestRequestMultipart:
    def test_success(self, cli):
        response_data = {"text": "Hello from Whisper"}
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps(response_data).encode()

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = cli._request_multipart(
                "/audio/transcriptions", "test.wav", b"fake-audio", "audio/wav"
            )

        assert result == response_data


# ---------------------------------------------------------------------------
# _request_audio
# ---------------------------------------------------------------------------
class TestRequestAudio:
    def test_success(self, cli):
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = b"RIFF....WAV"

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = cli._request_audio("/audio/speech", {"input": "hi", "voice": "af_heart"})

        assert result == b"RIFF....WAV"


# ---------------------------------------------------------------------------
# _chat
# ---------------------------------------------------------------------------
class TestChat:
    def test_returns_assistant_content(self, cli):
        with patch.object(
            cli,
            "_request_json",
            return_value={"choices": [{"message": {"content": "I am an AI."}}]},
        ):
            reply = cli._chat([{"role": "user", "content": "who are you?"}])

        assert reply == "I am an AI."

    def test_malformed_response_raises_value_error(self, cli):
        with patch.object(cli, "_request_json", return_value={}):
            with pytest.raises(ValueError, match="Unexpected API response format"):
                cli._chat([{"role": "user", "content": "hi"}])


# ---------------------------------------------------------------------------
# _tts
# ---------------------------------------------------------------------------
class TestTts:
    def test_writes_wav_file(self, cli, tmp_path):
        audio_bytes = b"RIFF....WAV"
        with patch.object(cli, "_request_audio", return_value=audio_bytes):
            with patch("builtins.open", mock_open()) as m:
                cli._tts("Hello world")

        m.assert_called_once_with("speech.wav", "wb")
        handle = m()
        handle.write.assert_called_once_with(audio_bytes)


# ---------------------------------------------------------------------------
# _stt
# ---------------------------------------------------------------------------
class TestStt:
    def test_file_not_found(self, cli):
        result = cli._stt("/nonexistent/path/audio.wav")
        assert "File not found" in result

    def test_returns_transcription(self, cli, tmp_path):
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake-audio")

        with patch.object(cli, "_request_multipart", return_value={"text": "transcribed text"}):
            result = cli._stt(str(audio_file))

        assert result == "transcribed text"

    def test_missing_text_key(self, cli, tmp_path):
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake-audio")

        with patch.object(cli, "_request_multipart", return_value={}):
            result = cli._stt(str(audio_file))

        assert result == "(no transcription returned)"


# ---------------------------------------------------------------------------
# main() — interactive loop
# ---------------------------------------------------------------------------
class TestMain:
    def _run(self, cli, inputs: list[str]):
        """Run main() feeding `inputs` line by line, return stdout."""
        with patch("builtins.input", side_effect=inputs + [EOFError]):
            cli.main()

    def test_exit_command(self, cli, capsys):
        self._run(cli, ["/exit"])
        out = capsys.readouterr().out
        assert "Goodbye!" in out

    def test_quit_command(self, cli, capsys):
        self._run(cli, ["quit"])
        out = capsys.readouterr().out
        assert "Goodbye!" in out

    def test_help_command(self, cli, capsys):
        self._run(cli, ["/help", "/exit"])
        out = capsys.readouterr().out
        assert "/tts" in out
        assert "/stt" in out

    def test_clear_command(self, cli, capsys):
        self._run(cli, ["/clear", "/exit"])
        out = capsys.readouterr().out
        assert "Chat history cleared." in out

    def test_empty_input_skipped(self, cli, capsys):
        """Empty lines do not call the API."""
        with patch.object(cli, "_chat") as mock_chat:
            self._run(cli, ["", "/exit"])
        mock_chat.assert_not_called()

    def test_chat_message(self, cli, capsys):
        with patch.object(cli, "_chat", return_value="Mocked reply"):
            self._run(cli, ["Hello there", "/exit"])
        out = capsys.readouterr().out
        assert "Mocked reply" in out

    def test_chat_error_removes_message(self, cli, capsys):
        import urllib.error

        with patch.object(cli, "_chat", side_effect=urllib.error.URLError("conn refused")):
            self._run(cli, ["Hello", "/exit"])
        out = capsys.readouterr().out
        assert "Chat error" in out

    def test_tts_command(self, cli, capsys):
        with patch.object(cli, "_tts") as mock_tts:
            self._run(cli, ["/tts Say something", "/exit"])
        mock_tts.assert_called_once_with("Say something")

    def test_tts_missing_text(self, cli, capsys):
        with patch.object(cli, "_tts") as mock_tts:
            self._run(cli, ["/tts", "/exit"])
        mock_tts.assert_not_called()
        out = capsys.readouterr().out
        assert "Usage: /tts" in out

    def test_tts_error(self, cli, capsys):
        import urllib.error

        with patch.object(cli, "_tts", side_effect=urllib.error.URLError("conn refused")):
            self._run(cli, ["/tts hello", "/exit"])
        out = capsys.readouterr().out
        assert "TTS error" in out

    def test_stt_command(self, cli, capsys, tmp_path):
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake")
        with patch.object(cli, "_stt", return_value="transcribed") as mock_stt:
            self._run(cli, [f"/stt {audio_file}", "/exit"])
        mock_stt.assert_called_once_with(str(audio_file))
        out = capsys.readouterr().out
        assert "transcribed" in out

    def test_stt_missing_filepath(self, cli, capsys):
        with patch.object(cli, "_stt") as mock_stt:
            self._run(cli, ["/stt", "/exit"])
        mock_stt.assert_not_called()
        out = capsys.readouterr().out
        assert "Usage: /stt" in out

    def test_stt_error(self, cli, capsys):
        import urllib.error

        with patch.object(cli, "_stt", side_effect=urllib.error.URLError("conn refused")):
            self._run(cli, ["/stt /nonexistent.wav", "/exit"])
        out = capsys.readouterr().out
        assert "STT error" in out

    def test_keyboard_interrupt(self, cli, capsys):
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            cli.main()
        err = capsys.readouterr().err
        assert "Exiting" in err

    def test_chat_value_error_is_reported(self, cli, capsys):
        with patch.object(cli, "_chat", side_effect=ValueError("bad response")):
            self._run(cli, ["hello", "/exit"])
        out = capsys.readouterr().out
        assert "Chat error" in out


# ---------------------------------------------------------------------------
# main() — startup validation
# ---------------------------------------------------------------------------
class TestMainStartup:
    def test_exits_when_api_key_missing(self, capsys):
        cli = _import_cli(api_key="")
        # Patch os.environ to also clear OPENAI_API_KEY so module sees no key
        with patch.dict(os.environ, {"LOCAL_API_KEY": "", "OPENAI_API_KEY": ""}, clear=False):
            cli.API_KEY = ""
            with pytest.raises(SystemExit) as exc_info:
                cli.main()
        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "LOCAL_API_KEY" in err


# ---------------------------------------------------------------------------
# _stt — content-type detection
# ---------------------------------------------------------------------------
class TestSttContentType:
    def test_mp3_content_type(self, cli, tmp_path):
        mp3_file = tmp_path / "audio.mp3"
        mp3_file.write_bytes(b"fake-mp3")
        captured = {}

        def fake_multipart(path, filename, file_bytes, content_type):
            captured["content_type"] = content_type
            return {"text": "hello"}

        with patch.object(cli, "_request_multipart", side_effect=fake_multipart):
            cli._stt(str(mp3_file))

        assert captured["content_type"] == "audio/mpeg"

    def test_unknown_extension_defaults_to_audio_wav(self, cli, tmp_path):
        unknown_file = tmp_path / "audio.unknownext"
        unknown_file.write_bytes(b"fake")
        captured = {}

        def fake_multipart(path, filename, file_bytes, content_type):
            captured["content_type"] = content_type
            return {"text": "hello"}

        with patch.object(cli, "_request_multipart", side_effect=fake_multipart):
            cli._stt(str(unknown_file))

        assert captured["content_type"] == "audio/wav"
