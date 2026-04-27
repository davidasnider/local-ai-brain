import json
import sys
from unittest.mock import MagicMock, mock_open, patch

import pytest

from local_ai_brain.cli import chat, get_api_key, get_base_url, main, stt, tts


# ANSI code tests
def test_get_api_key(monkeypatch):
    monkeypatch.setenv("LOCAL_API_KEY", "test_key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert get_api_key() == "test_key"


def test_get_api_key_openai_fallback(monkeypatch):
    monkeypatch.delenv("LOCAL_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "fallback_key")
    assert get_api_key() == "fallback_key"


def test_get_api_key_missing(monkeypatch):
    monkeypatch.delenv("LOCAL_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with patch("sys.exit") as mock_exit:
        with patch("builtins.print") as mock_print:
            get_api_key()
            mock_print.assert_called_once()
            mock_exit.assert_called_once_with(1)


def test_get_base_url(monkeypatch):
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)
    assert get_base_url() == "http://localhost:8000/v1"

    monkeypatch.setenv("OPENAI_API_BASE", "http://test:9000/v1")
    assert get_base_url() == "http://test:9000/v1"


@patch("urllib.request.urlopen")
def test_tts_success(mock_urlopen):
    mock_response = MagicMock()
    mock_response.read.return_value = b"audio_data"
    mock_response.__enter__.return_value = mock_response
    mock_urlopen.return_value = mock_response

    with patch("builtins.open", mock_open()) as mocked_file:
        tts("Hello world", "http://base", "key")
        mocked_file.assert_called_once_with("speech.wav", "wb")
        mocked_file().write.assert_called_once_with(b"audio_data")


@patch("urllib.request.urlopen")
def test_tts_error(mock_urlopen, capsys):
    mock_urlopen.side_effect = Exception("Test Error")
    tts("Hello world", "http://base", "key")
    captured = capsys.readouterr()
    assert "TTS Error: Test Error" in captured.out


@patch("os.path.exists")
@patch("urllib.request.urlopen")
def test_stt_success(mock_urlopen, mock_exists):
    mock_exists.return_value = True
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"text": "Hello text"}).encode("utf-8")
    mock_response.__enter__.return_value = mock_response
    mock_urlopen.return_value = mock_response

    with patch("builtins.open", mock_open(read_data=b"filedata")):
        with patch("builtins.print") as mock_print:
            stt("dummy.wav", "http://base", "key")
            # Should print transcription
            assert any(
                "Transcription: Hello text" in call.args[0] for call in mock_print.call_args_list
            )


@patch("os.path.exists")
def test_stt_file_not_found(mock_exists, capsys):
    mock_exists.return_value = False
    stt("missing.wav", "http://base", "key")
    captured = capsys.readouterr()
    assert "Error: File not found: missing.wav" in captured.out


@patch("os.path.exists")
@patch("urllib.request.urlopen")
def test_stt_error(mock_urlopen, mock_exists, capsys):
    mock_exists.return_value = True
    mock_urlopen.side_effect = Exception("Test STT Error")
    with patch("builtins.open", mock_open(read_data=b"filedata")):
        stt("dummy.wav", "http://base", "key")
        captured = capsys.readouterr()
        assert "STT Error: Test STT Error" in captured.out


@patch("urllib.request.urlopen")
def test_chat_success(mock_urlopen):
    mock_response = MagicMock()
    # Simulate Server-Sent Events
    lines = [
        b'data: {"choices": [{"delta": {"content": "Hello"}}]}\n',
        b'data: {"choices": [{"delta": {"content": " World"}}]}\n',
        b"data: [DONE]\n",
    ]
    mock_response.__iter__.return_value = lines
    mock_response.__enter__.return_value = mock_response
    mock_urlopen.return_value = mock_response

    with patch("builtins.print"):
        response = chat([{"role": "user", "content": "Hi"}], "http://base", "key")
        assert response == "Hello World"


@patch("urllib.request.urlopen")
def test_chat_error(mock_urlopen, capsys):
    mock_urlopen.side_effect = Exception("Test Chat Error")
    response = chat([{"role": "user", "content": "Hi"}], "http://base", "key")
    assert response is None
    captured = capsys.readouterr()
    assert "Chat Error: Test Chat Error" in captured.out


@patch("sys.exit")
def test_main_help(mock_exit, capsys):
    # mock_exit side effect to raise an Exception so main terminates
    mock_exit.side_effect = SystemExit(0)
    with patch.object(sys, "argv", ["local-brain", "--help-cmd"]):
        with pytest.raises(SystemExit):
            main()
        mock_exit.assert_called_once_with(0)
        captured = capsys.readouterr()
        assert "Local AI Brain CLI" in captured.out


@patch("local_ai_brain.cli.get_api_key", return_value="key")
@patch("local_ai_brain.cli.get_base_url", return_value="http://base")
@patch("builtins.input")
def test_main_exit(mock_input, mock_base, mock_key):
    with patch.object(sys, "argv", ["local-brain"]):
        mock_input.side_effect = ["/exit"]
        main()


@patch("local_ai_brain.cli.get_api_key", return_value="key")
@patch("local_ai_brain.cli.get_base_url", return_value="http://base")
@patch("builtins.input")
def test_main_keyboard_interrupt(mock_input, mock_base, mock_key):
    with patch.object(sys, "argv", ["local-brain"]):
        mock_input.side_effect = KeyboardInterrupt()
        main()


@patch("local_ai_brain.cli.get_api_key", return_value="key")
@patch("local_ai_brain.cli.get_base_url", return_value="http://base")
@patch("builtins.input")
@patch("local_ai_brain.cli.chat")
def test_main_commands(mock_chat, mock_input, mock_base, mock_key, capsys):
    with patch.object(sys, "argv", ["local-brain"]):
        mock_input.side_effect = [
            "",  # empty input
            "/help",  # help cmd
            "/clear",  # clear cmd
            "/tts text",  # tts cmd
            "/stt file.wav",  # stt cmd
            "/unknown",  # unknown cmd
            "hello",  # chat message
            "/exit",  # exit
        ]

        with patch("local_ai_brain.cli.tts") as mock_tts:
            with patch("local_ai_brain.cli.stt") as mock_stt:
                mock_chat.return_value = "hi"
                main()

                mock_tts.assert_called_once_with("text", "http://base", "key")
                mock_stt.assert_called_once_with("file.wav", "http://base", "key")
                mock_chat.assert_called_once()
                # Check chat messages structure
                messages = mock_chat.call_args[0][0]
                assert messages[0] == {"role": "user", "content": "hello"}


@patch("local_ai_brain.cli.get_api_key", return_value="key")
@patch("local_ai_brain.cli.get_base_url", return_value="http://base")
@patch("builtins.input")
def test_main_invalid_tts_stt(mock_input, mock_base, mock_key, capsys):
    with patch.object(sys, "argv", ["local-brain"]):
        # Pass unknown command as well to trigger unknown command logic
        mock_input.side_effect = ["/tts  ", "/stt  ", "/unknown", "/exit"]
        main()
        captured = capsys.readouterr()
        assert "Usage: /tts <text>" in captured.out
        assert "Usage: /stt <filepath>" in captured.out
        assert "Unknown command." in captured.out
