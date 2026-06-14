import json
import signal
import subprocess
import sys
import urllib.error
from unittest.mock import MagicMock, mock_open, patch

import pytest

from local_ai_brain.cli import (
    chat,
    get_active_client_pids,
    get_api_key,
    get_base_url,
    main,
    stt,
    trace,
    tts,
)


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
        mock_exit.side_effect = SystemExit(1)
        with patch("builtins.print") as mock_print:
            with pytest.raises(SystemExit):
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
    mock_response.read.side_effect = [b"audio_data", b""]
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


@patch("os.path.getsize")
@patch("os.path.exists")
@patch("urllib.request.urlopen")
def test_stt_success(mock_urlopen, mock_exists, mock_getsize):
    mock_exists.return_value = True
    mock_getsize.return_value = 1000
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


@patch("os.path.getsize")
@patch("os.path.exists")
def test_stt_file_too_large(mock_exists, mock_getsize, capsys):
    mock_exists.return_value = True
    mock_getsize.return_value = 30 * 1024 * 1024  # 30MB
    stt("large.wav", "http://base", "key")
    captured = capsys.readouterr()
    assert "Error: File too large (> 25MB)" in captured.out


@patch("os.path.getsize")
@patch("os.path.exists")
@patch("urllib.request.urlopen")
def test_stt_error(mock_urlopen, mock_exists, mock_getsize, capsys):
    mock_exists.return_value = True
    mock_getsize.return_value = 1000
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


@patch("urllib.request.urlopen")
def test_tts_with_model_env(mock_urlopen, monkeypatch):
    monkeypatch.setenv("LOCAL_BRAIN_TTS_MODEL", "custom-tts-model")
    mock_response = MagicMock()
    mock_response.read.side_effect = [b"audio_data", b""]
    mock_response.__enter__.return_value = mock_response
    mock_urlopen.return_value = mock_response

    with patch("builtins.open", mock_open()):
        tts("Hello world", "http://base", "key")
        # Check that the model was included in the request data
        args, kwargs = mock_urlopen.call_args
        req = args[0]
        data = json.loads(req.data.decode("utf-8"))
        assert data["model"] == "custom-tts-model"


@patch("urllib.request.urlopen")
def test_chat_with_model_env(mock_urlopen, monkeypatch):
    monkeypatch.setenv("LOCAL_BRAIN_CHAT_MODEL", "custom-chat-model")
    mock_response = MagicMock()
    mock_response.__iter__.return_value = [b"data: [DONE]\n"]
    mock_response.__enter__.return_value = mock_response
    mock_urlopen.return_value = mock_response

    with patch("builtins.print"):
        chat([{"role": "user", "content": "Hi"}], "http://base", "key")
        args, kwargs = mock_urlopen.call_args
        req = args[0]
        data = json.loads(req.data.decode("utf-8"))
        assert data["model"] == "custom-chat-model"


@patch("urllib.request.urlopen")
def test_chat_json_decode_error(mock_urlopen, capsys):
    mock_response = MagicMock()
    mock_response.__iter__.return_value = [b"data: invalid-json\n", b"data: [DONE]\n"]
    mock_response.__enter__.return_value = mock_response
    mock_urlopen.return_value = mock_response

    with patch("builtins.print"):
        chat([{"role": "user", "content": "Hi"}], "http://base", "key")
        # Should not crash and should skip the invalid JSON


@patch("os.path.getsize")
@patch("os.path.exists")
@patch("urllib.request.urlopen")
def test_stt_streaming_read(mock_urlopen, mock_exists, mock_getsize):
    mock_exists.return_value = True
    mock_getsize.return_value = 100
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"text": "done"}).encode("utf-8")
    mock_response.__enter__.return_value = mock_response
    mock_urlopen.return_value = mock_response

    with patch("builtins.open", mock_open(read_data=b"filedata")):
        stt("dummy.wav", "http://base", "key")
        args, kwargs = mock_urlopen.call_args
        req = args[0]
        # Read from StreamingBody to ensure all paths are covered
        body = req.data
        chunk1 = body.read(10)
        assert len(chunk1) == 10
        chunk2 = body.read()  # read the rest
        assert len(chunk2) > 0
        assert body.read() == b""  # EOF


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


@patch("urllib.request.urlopen")
def test_tts_http_error(mock_urlopen, capsys):
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"detail": "TTS specific error"}).encode("utf-8")
    err = urllib.error.HTTPError("http://base", 400, "Bad Request", {}, mock_response)
    mock_urlopen.side_effect = err

    tts("Hello world", "http://base", "key")
    captured = capsys.readouterr()
    assert "TTS HTTP Error: 400 - TTS specific error" in captured.out


@patch("os.path.getsize")
@patch("os.path.exists")
@patch("urllib.request.urlopen")
def test_stt_http_error(mock_urlopen, mock_exists, mock_getsize, capsys):
    mock_exists.return_value = True
    mock_getsize.return_value = 1000
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"detail": "STT specific error"}).encode("utf-8")
    err = urllib.error.HTTPError("http://base", 401, "Unauthorized", {}, mock_response)
    mock_urlopen.side_effect = err

    with patch("builtins.open", mock_open(read_data=b"filedata")):
        stt("dummy.wav", "http://base", "key")
        captured = capsys.readouterr()
        assert "STT HTTP Error: 401 - STT specific error" in captured.out


@patch("urllib.request.urlopen")
def test_chat_http_error(mock_urlopen, capsys):
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"detail": "Chat specific error"}).encode("utf-8")
    err = urllib.error.HTTPError("http://base", 503, "Service Unavailable", {}, mock_response)
    mock_urlopen.side_effect = err

    response = chat([{"role": "user", "content": "Hi"}], "http://base", "key")
    assert response is None
    captured = capsys.readouterr()
    assert "Chat HTTP Error: 503 - Chat specific error" in captured.out


@patch("urllib.request.urlopen")
def test_tts_http_error_non_json(mock_urlopen, capsys):
    mock_response = MagicMock()
    mock_response.read.side_effect = Exception("Not JSON")
    err = urllib.error.HTTPError("http://base", 500, "Internal Server Error", {}, mock_response)
    mock_urlopen.side_effect = err

    tts("Hello world", "http://base", "key")
    captured = capsys.readouterr()
    assert "TTS HTTP Error: 500 - Internal Server Error" in captured.out


@patch("time.sleep")
@patch("subprocess.Popen")
def test_main_serve(mock_popen, mock_sleep, capsys, monkeypatch):
    monkeypatch.setenv("LOCAL_API_KEY", "test-key")
    monkeypatch.setenv("TESTING", "1")
    mock_sleep.side_effect = KeyboardInterrupt()

    mock_process = MagicMock()
    mock_process.poll.return_value = None
    mock_popen.return_value = mock_process

    with patch.object(sys, "argv", ["local-brain", "serve"]):
        with pytest.raises(SystemExit) as e:
            main()
        assert e.value.code == 0

    assert mock_popen.call_count == 4
    assert mock_process.terminate.call_count == 4
    assert mock_process.wait.call_count == 4

    # Verify LLM Server command uses our internal wrapper
    llm_call = mock_popen.call_args_list[0]
    cmd = llm_call.args[0]
    assert "local_ai_brain.models.llm_server" in cmd
    assert "--host" in cmd
    assert "127.0.0.1" in cmd
    assert "--port" in cmd
    assert "8001" in cmd


@patch("time.sleep")
@patch("subprocess.Popen")
def test_main_serve_subprocess_restart(mock_popen, mock_sleep, capsys, monkeypatch):
    """Verify that a crashing subprocess is restarted."""
    monkeypatch.setenv("LOCAL_API_KEY", "test-key")
    monkeypatch.setenv("TESTING", "1")

    # Create distinct mock processes for each service
    p1 = MagicMock(name="p1")
    p2 = MagicMock(name="p2")
    p3 = MagicMock(name="p3")
    p4 = MagicMock(name="p4")
    p1_restart = MagicMock(name="p1_restart")

    # p1 will crash (return 1 on poll), others stay running (return None)
    p1.poll.return_value = 1
    p2.poll.return_value = None
    p3.poll.return_value = None
    p4.poll.return_value = None
    p1_restart.poll.return_value = None

    # subprocess.Popen will return p1, p2, p3, p4 in order, then p1_restart
    mock_popen.side_effect = [p1, p2, p3, p4, p1_restart]

    # First sleep is the 5s restart delay, second sleep triggers shutdown
    mock_sleep.side_effect = [None, KeyboardInterrupt()]

    with patch.object(sys, "argv", ["local-brain", "serve"]):
        with pytest.raises(SystemExit):
            main()

    # Should have started 4 initial + 1 restart = 5
    assert mock_popen.call_count == 5
    captured = capsys.readouterr()
    assert "exited unexpectedly" in captured.out
    assert "Restarting in 5s" in captured.out


@patch("subprocess.check_output")
def test_get_active_client_pids(mock_check_output):
    mock_check_output.return_value = (
        b"COMMAND     PID USER   FD   TYPE             DEVICE SIZE/OFF NODE NAME\n"
        b"Python    12345 user   3u  IPv4 0xdeadbeef      0t0  "
        b"TCP 127.0.0.1:54321->127.0.0.1:8000 (ESTABLISHED)\n"
    )
    pids = get_active_client_pids([8000])
    assert pids == {54321: 12345}


@patch("subprocess.check_output")
def test_get_active_client_pids_empty(mock_check_output):
    mock_check_output.return_value = b""
    pids = get_active_client_pids([8000])
    assert pids == {}


@patch("subprocess.check_output")
def test_get_active_client_pids_error(mock_check_output):
    mock_check_output.side_effect = subprocess.CalledProcessError(1, "lsof")
    pids = get_active_client_pids([8000])
    assert pids == {}


@patch("os.path.exists")
@patch("builtins.open", new_callable=mock_open)
@patch("local_ai_brain.cli.get_active_client_pids")
@patch("subprocess.check_output")
@patch("select.select")
def test_trace_basic(mock_select, mock_check_output, mock_pids, mock_file, mock_exists, capsys):
    mock_exists.return_value = True
    mock_pids.return_value = {54321: 12345}

    mock_check_output.return_value = b"python app.py\n"

    # Mock log file content
    handle = mock_file()
    handle.readline.side_effect = [
        "2023-01-01 12:00:00.000 | INFO     | local_ai_brain.main:proxy_request:146 - "
        'Incoming chat from 127.0.0.1:54321 - "Hello test"\n',
        "",  # End of loop iteration
    ]

    # Trigger KeyboardInterrupt after first iteration
    mock_select.side_effect = KeyboardInterrupt()

    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = True
    with patch("sys.stdin", mock_stdin):
        with pytest.raises(SystemExit):
            trace()

    captured = capsys.readouterr()
    assert "[PID 12345]" in captured.out
    assert "python app.py" in captured.out
    assert "Says:" in captured.out
    assert "Hello test" in captured.out


@patch("os.path.exists")
@patch("builtins.open", new_callable=mock_open)
@patch("local_ai_brain.cli.get_active_client_pids")
@patch("select.select")
@patch("os.kill")
@patch("subprocess.check_output")
def test_trace_kill(
    mock_check_output, mock_kill, mock_select, mock_pids, mock_file, mock_exists, capsys
):
    mock_exists.return_value = True
    mock_pids.return_value = {54321: 9999}
    mock_check_output.return_value = b"test-command\n"

    # Mock select to return stdin available twice
    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = True
    mock_stdin.readline.side_effect = ["k\n", "9999\n"]

    # Use patch to replace sys.stdin
    with patch("sys.stdin", mock_stdin):
        # Mock log file content
        handle = mock_file()
        handle.readline.side_effect = [
            "2023-01-01 12:00:00.000 | INFO     | local_ai_brain.main:proxy_request:146 - "
            'Incoming chat from 127.0.0.1:54321 - "Hello test"\n',
            "",  # End of loop iteration
            "",
        ]
        mock_select.side_effect = [
            ([mock_stdin], [], []),
            ([mock_stdin], [], []),
            KeyboardInterrupt(),
        ]

        with pytest.raises(SystemExit):
            trace()

        mock_kill.assert_called_with(9999, signal.SIGKILL)
        captured = capsys.readouterr()
        assert "Successfully killed PID 9999" in captured.out


@patch("os.path.exists")
@patch("builtins.open", new_callable=mock_open)
@patch("select.select")
def test_trace_stdin_eof(mock_select, mock_file, mock_exists):
    mock_exists.return_value = True

    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = True
    mock_stdin.readline.return_value = ""

    with patch("sys.stdin", mock_stdin):
        mock_file().readline.return_value = ""
        mock_select.return_value = ([mock_stdin], [], [])

        # Should return cleanly without spinning or throwing an error
        trace()


@patch("os.path.exists")
@patch("builtins.open", new_callable=mock_open)
@patch("local_ai_brain.cli.get_active_client_pids")
@patch("select.select")
@patch("os.kill")
def test_trace_kill_untracked(mock_kill, mock_select, mock_pids, mock_file, mock_exists, capsys):
    mock_exists.return_value = True
    mock_pids.return_value = {}

    # Mock select to return stdin available twice
    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = True
    mock_stdin.readline.side_effect = ["k\n", "9999\n"]

    # Use patch to replace sys.stdin
    with patch("sys.stdin", mock_stdin):
        mock_file().readline.return_value = ""
        mock_select.side_effect = [
            ([mock_stdin], [], []),
            ([mock_stdin], [], []),
            KeyboardInterrupt(),
        ]

        with pytest.raises(SystemExit):
            trace()

        mock_kill.assert_not_called()
        captured = capsys.readouterr()
        assert "PID not tracked by this trace session" in captured.out


@patch("os.path.exists")
@patch("builtins.open", new_callable=mock_open)
@patch("local_ai_brain.cli.get_active_client_pids")
@patch("subprocess.check_output")
@patch("select.select")
def test_trace_non_tty(mock_select, mock_check_output, mock_pids, mock_file, mock_exists, capsys):
    mock_exists.return_value = True
    mock_pids.return_value = {54321: 12345}
    mock_check_output.return_value = b"python app.py\n"

    # Mock log file content
    handle = mock_file()
    handle.readline.side_effect = [
        "2023-01-01 12:00:00.000 | INFO     | local_ai_brain.main:proxy_request:146 - "
        'Incoming chat from 127.0.0.1:54321 - "Hello non-tty"\n',
        KeyboardInterrupt(),
    ]

    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = False

    with patch("sys.stdin", mock_stdin):
        with pytest.raises(SystemExit):
            trace()

    mock_select.assert_not_called()
    captured = capsys.readouterr()
    assert "[PID 12345]" in captured.out
    assert "Says:" in captured.out
    assert "Hello non-tty" in captured.out


@patch("os.path.exists")
@patch("builtins.open", new_callable=mock_open)
@patch("local_ai_brain.cli.get_active_client_pids")
@patch("select.select")
@patch("os.kill")
def test_trace_kill_recycled(mock_kill, mock_select, mock_pids, mock_file, mock_exists, capsys):
    mock_exists.return_value = True

    # First, the PID is tracked
    # Second, it is NOT in the returned active client pids when re-read
    mock_pids.side_effect = [
        {54321: 9999},  # First refresh
        {},  # Subsequent read
    ]

    # Mock select to return stdin available twice
    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = True
    mock_stdin.readline.side_effect = ["k\n", "9999\n"]

    # Use patch to replace sys.stdin
    with patch("sys.stdin", mock_stdin):
        # Mock log file content
        handle = mock_file()
        handle.readline.side_effect = [
            "2023-01-01 12:00:00.000 | INFO     | local_ai_brain.main:proxy_request:146 - "
            'Incoming chat from 127.0.0.1:54321 - "Hello test"\n',
            "",  # End of loop iteration
            "",
        ]
        mock_select.side_effect = [
            ([mock_stdin], [], []),
            ([mock_stdin], [], []),
            KeyboardInterrupt(),
        ]

        with pytest.raises(SystemExit):
            trace()

        mock_kill.assert_called_with(9999, signal.SIGKILL)
        captured = capsys.readouterr()
        assert "Successfully killed PID 9999" in captured.out


@patch("os.path.exists")
@patch("builtins.open")
@patch("local_ai_brain.cli.get_active_client_pids")
@patch("select.select")
@patch("os.stat")
@patch("os.fstat")
def test_trace_log_rotation(
    mock_fstat, mock_stat, mock_select, mock_pids, mock_open_fn, mock_exists
):
    mock_exists.return_value = True
    mock_pids.return_value = {}
    mock_select.side_effect = KeyboardInterrupt()

    # Mock fstat for the initial file descriptor to return inode 123
    mock_fstat_initial = MagicMock()
    mock_fstat_initial.st_ino = 123
    mock_fstat.return_value = mock_fstat_initial

    # Mock file handles
    file1 = MagicMock()
    file1.readline.return_value = ""
    file1.tell.return_value = 0

    file2 = MagicMock()
    file2.readline.return_value = ""
    file2.tell.return_value = 0

    # Mock open to return file1 first, then file2 upon reopening
    mock_open_fn.side_effect = [file1, file2]

    # Mock stat for the path to return inode 456 (simulating rotation)
    mock_stat_info = MagicMock()
    mock_stat_info.st_ino = 456
    mock_stat_info.st_size = 0
    mock_stat.return_value = mock_stat_info

    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = True

    # Use patch to replace sys.stdin
    with patch("sys.stdin", mock_stdin):
        # We want time.time() to simulate time passing so that rotation check runs
        with patch("time.time") as mock_time:
            # 1. Start time
            # 2. Time during loop iteration (passed 2.0s)
            # 3. Time for logging refresh or whatever
            mock_time.side_effect = [1000.0, 1003.0, 1004.0, 1005.0]

            # Mock fstat to return inode 456 when the new file is opened
            mock_fstat_new = MagicMock()
            mock_fstat_new.st_ino = 456
            mock_fstat.side_effect = [mock_fstat_initial, mock_fstat_new]

            with pytest.raises(SystemExit):
                trace()

    # Verify that open was called twice (once for initial, once for reopened)
    assert mock_open_fn.call_count == 2
    # Verify that the old file was closed
    file1.close.assert_called_once()


@patch("os.path.exists")
@patch("builtins.open", new_callable=mock_open)
@patch("local_ai_brain.cli.get_active_client_pids")
@patch("select.select")
@patch("os.kill")
def test_trace_prunes_dead_pids(mock_kill, mock_select, mock_pids, mock_file, mock_exists):
    mock_exists.return_value = True
    mock_pids.return_value = {54321: 9999, 54322: 8888}

    def kill_side_effect(pid, sig):
        if sig == 0:
            if pid == 9999:
                raise ProcessLookupError("No such process")
            return None
        return None

    mock_kill.side_effect = kill_side_effect

    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = True
    mock_stdin.readline.side_effect = ["k\n", "9999\n"]

    with patch("sys.stdin", mock_stdin):
        handle = mock_file()
        log_line_1 = (
            "2023-01-01 12:00:00.000 | INFO     | "
            "local_ai_brain.main:proxy_request:146 - "
            'Incoming chat from 127.0.0.1:54321 - "Hello test"\n'
        )
        log_line_2 = (
            "2023-01-01 12:00:00.000 | INFO     | "
            "local_ai_brain.main:proxy_request:146 - "
            'Incoming chat from 127.0.0.1:54322 - "Hello test 2"\n'
        )
        handle.readline.side_effect = [
            log_line_1,
            log_line_2,
            "",
            "",
            "",
        ]

        class TimeSimulator:
            def __init__(self):
                self.val = 1000.0

            def __call__(self):
                self.val += 6.0
                return self.val

        with patch("time.time", new_callable=TimeSimulator):
            mock_select.side_effect = [
                ([], [], []),
                ([mock_stdin], [], []),
                ([mock_stdin], [], []),
                KeyboardInterrupt(),
            ]

            with pytest.raises(SystemExit):
                trace()

        for call in mock_kill.call_args_list:
            pid, sig = call[0]
            if pid == 9999:
                assert sig == 0


@patch("os.path.exists")
@patch("builtins.open", new_callable=mock_open)
@patch("local_ai_brain.cli.get_active_client_pids")
@patch("select.select")
@patch("os.kill")
def test_trace_kill_cancel(mock_kill, mock_select, mock_pids, mock_file, mock_exists, capsys):
    mock_exists.return_value = True
    mock_pids.return_value = {54321: 9999}

    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = True
    mock_stdin.readline.side_effect = ["k\n", "esc\n"]

    with patch("sys.stdin", mock_stdin):
        handle = mock_file()
        log_line_1 = (
            "2023-01-01 12:00:00.000 | INFO     | "
            "local_ai_brain.main:proxy_request:146 - "
            'Incoming chat from 127.0.0.1:54321 - "Hello test"\n'
        )
        handle.readline.side_effect = [
            log_line_1,
            "",
            "",
        ]
        mock_select.side_effect = [
            ([mock_stdin], [], []),
            ([mock_stdin], [], []),
            KeyboardInterrupt(),
        ]

        with pytest.raises(SystemExit):
            trace()

        for call in mock_kill.call_args_list:
            pid, sig = call[0]
            assert sig != signal.SIGKILL
        captured = capsys.readouterr()
        assert "Cancelled." in captured.out


@patch("os.path.exists")
@patch("os.path.getsize")
@patch("urllib.request.urlopen")
def test_stt_streaming_body_stop_iteration(mock_urlopen, mock_getsize, mock_exists):
    mock_exists.return_value = True
    mock_getsize.return_value = 100

    captured_streaming_body = None

    def mock_urlopen_fn(req, *args, **kwargs):
        nonlocal captured_streaming_body
        captured_streaming_body = req.data
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"text": "mocked"}'
        mock_response.__enter__.return_value = mock_response
        return mock_response

    mock_urlopen.side_effect = mock_urlopen_fn

    with patch("builtins.open", mock_open(read_data=b"small content")):
        stt("dummy.wav", "http://base", "key")

        assert captured_streaming_body is not None
        # Read everything from it within open mock context
        while True:
            chunk = captured_streaming_body.read(10)
            if not chunk:
                break

        # After it finishes, reading again should return b"" (raising and handling StopIteration)
        assert captured_streaming_body.read(10) == b""
        assert captured_streaming_body.read() == b""


@patch("os.path.exists")
@patch("os.path.getsize")
@patch("urllib.request.urlopen")
def test_stt_http_error_invalid_json(mock_urlopen, mock_getsize, mock_exists, capsys):
    mock_exists.return_value = True
    mock_getsize.return_value = 1000

    import io
    import urllib.error

    fp = io.BytesIO(b"not a valid json")
    err = urllib.error.HTTPError("http://base/audio/transcriptions", 400, "Bad Request", {}, fp)
    mock_urlopen.side_effect = err

    with patch("builtins.open", mock_open(read_data=b"filedata")):
        stt("dummy.wav", "http://base", "key")

    captured = capsys.readouterr()
    assert "STT HTTP Error: 400 - Bad Request" in captured.out


@patch("subprocess.check_output")
def test_get_active_client_pids_unexpected_exception(mock_check_output):
    mock_check_output.side_effect = RuntimeError("Unexpected subprocess failure")

    with patch("local_ai_brain.cli.logger") as mock_logger:
        pids = get_active_client_pids()
        assert pids == {}
        mock_logger.debug.assert_called_once()
        assert "Unexpected subprocess failure" in mock_logger.debug.call_args[0][0]


@patch("os.path.exists")
@patch("builtins.open", new_callable=mock_open)
@patch("local_ai_brain.cli.get_active_client_pids")
@patch("select.select")
@patch("os.kill")
def test_trace_interactive_kill_checks_liveness(
    mock_kill, mock_select, mock_pids, mock_file, mock_exists, capsys
):
    mock_exists.return_value = True
    mock_pids.return_value = {54321: 9999}

    # First call to os.kill(9999, 0) should raise ProcessLookupError
    def kill_side_effect(pid, sig):
        if sig == 0:
            raise ProcessLookupError("No such process")
        return None

    mock_kill.side_effect = kill_side_effect

    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = True
    mock_stdin.readline.side_effect = ["k\n", "9999\n"]

    with patch("sys.stdin", mock_stdin):
        handle = mock_file()
        log_line_1 = (
            "2023-01-01 12:00:00.000 | INFO     | "
            "local_ai_brain.main:proxy_request:146 - "
            'Incoming chat from 127.0.0.1:54321 - "Hello test"\n'
        )
        handle.readline.side_effect = [
            log_line_1,
            "",
            "",
        ]
        mock_select.side_effect = [
            ([mock_stdin], [], []),
            ([mock_stdin], [], []),
            KeyboardInterrupt(),
        ]

        with pytest.raises(SystemExit):
            trace()

        captured = capsys.readouterr()
        assert "Process has already exited" in captured.out
        # Verify sigkill was not sent
        for call in mock_kill.call_args_list:
            pid, sig = call[0]
            assert sig != signal.SIGKILL


@patch("os.path.exists")
@patch("builtins.open", new_callable=mock_open)
@patch("local_ai_brain.cli.get_active_client_pids")
@patch("subprocess.check_output")
@patch("select.select")
@patch("os.kill")
def test_trace_waiting_for_pid_mutes_incoming_messages(
    mock_kill, mock_select, mock_check_output, mock_pids, mock_file, mock_exists, capsys
):
    mock_exists.return_value = True
    mock_pids.return_value = {54321: 9999}
    mock_check_output.return_value = b"python app.py\n"

    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = True
    mock_stdin.readline.side_effect = ["k\n", "esc\n"]

    with patch("sys.stdin", mock_stdin):
        handle = mock_file()
        log_line_1 = (
            "2023-01-01 12:00:00.000 | INFO     | "
            "local_ai_brain.main:proxy_request:146 - "
            'Incoming chat from 127.0.0.1:54321 - "Hello test"\n'
        )
        handle.readline.side_effect = [
            "",
            log_line_1,
            "",
            "",
            "",
        ]

        mock_select.side_effect = [
            ([mock_stdin], [], []),
            ([], [], []),
            ([mock_stdin], [], []),
            KeyboardInterrupt(),
        ]

        with pytest.raises(SystemExit):
            trace()

        captured = capsys.readouterr()
        # Verify the message muted line was printed
        assert "[message received — finish entering PID first]" in captured.out
        # Verify the message was buffered and eventually displayed once input completed
        assert "[PID 9999]" in captured.out
        assert "Says:" in captured.out
        assert "Hello test" in captured.out


@patch("os.path.exists")
def test_trace_missing_log_file(mock_exists, capsys):
    mock_exists.return_value = False
    with pytest.raises(SystemExit) as excinfo:
        trace()
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Log file not found" in captured.out


@patch("subprocess.check_output")
def test_get_active_client_pids_from_settings(mock_check_output, monkeypatch):
    monkeypatch.setenv("OPENAI_API_BASE", "http://localhost:9000/v1")
    with patch("local_ai_brain.config.settings") as mock_settings:
        mock_settings.VLLM_URL = "http://127.0.0.1:9001"
        mock_settings.STT_URL = "http://127.0.0.1:9002"
        mock_settings.TTS_URL = "http://127.0.0.1:9003"

        mock_check_output.return_value = b""
        get_active_client_pids()

        args, kwargs = mock_check_output.call_args
        cmd = args[0]
        port_arg = cmd[1]
        assert "9001" in port_arg
        assert "9002" in port_arg
        assert "9003" in port_arg
        assert "9000" in port_arg


@patch("subprocess.check_output")
def test_get_active_client_pids_fallback_on_import_error(mock_check_output):
    with patch.dict("sys.modules", {"local_ai_brain.config": None}):
        mock_check_output.return_value = b""
        get_active_client_pids()

        args, kwargs = mock_check_output.call_args
        cmd = args[0]
        port_arg = cmd[1]
        for p in ["8000", "8001", "8002", "8003"]:
            assert p in port_arg


@patch("os.path.exists")
@patch("builtins.open", new_callable=mock_open)
@patch("local_ai_brain.cli.get_active_client_pids")
@patch("subprocess.check_output")
@patch("select.select")
def test_trace_spoofed_port_in_prompt(
    mock_select, mock_check_output, mock_pids, mock_file, mock_exists, capsys
):
    mock_exists.return_value = True
    mock_pids.return_value = {54321: 12345, 9999: 99999}
    mock_check_output.return_value = b"python app.py\n"

    spoofed_log_line = (
        "2023-01-01 12:00:00.000 | INFO     | local_ai_brain.main:proxy_request:146 - "
        'Incoming chat from 127.0.0.1:54321 - "Incoming chat from 127.0.0.1:9999 - \\"Spoof\\""\n'
    )
    handle = mock_file()
    handle.readline.side_effect = [
        spoofed_log_line,
        "",
    ]
    mock_select.side_effect = KeyboardInterrupt()

    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = True
    with patch("sys.stdin", mock_stdin):
        with pytest.raises(SystemExit):
            trace()

    captured = capsys.readouterr()
    assert "[PID 12345]" in captured.out
    assert "[PID 99999]" not in captured.out


@patch("os.path.exists")
@patch("builtins.open", new_callable=mock_open)
@patch("local_ai_brain.cli.get_active_client_pids")
@patch("subprocess.check_output")
@patch("select.select")
@patch("time.sleep")
def test_trace_partial_line_seek_back(
    mock_sleep, mock_select, mock_check_output, mock_pids, mock_file, mock_exists, capsys
):
    mock_exists.return_value = True
    mock_pids.return_value = {54321: 12345}
    mock_check_output.return_value = b"python app.py\n"

    handle = mock_file()

    positions = [0, 0, 80]

    def tell_side_effect():
        return positions.pop(0) if positions else 100

    handle.tell.side_effect = tell_side_effect

    partial_line = (
        "2023-01-01 12:00:00.000 | INFO     | "
        "local_ai_brain.main:proxy_request:146 - Incoming chat from 127.0.0.1:"
    )
    full_line = partial_line + '54321 - "Hello complete"\n'

    handle.readline.side_effect = [
        partial_line,
        full_line,
        "",
    ]

    mock_select.side_effect = KeyboardInterrupt()

    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = True
    with patch("sys.stdin", mock_stdin):
        with pytest.raises(SystemExit):
            trace()

    captured = capsys.readouterr()
    assert "[PID 12345]" in captured.out
    assert "Hello complete" in captured.out

    handle.seek.assert_any_call(0)
    mock_sleep.assert_any_call(0.05)
