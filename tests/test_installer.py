import os
import re
import subprocess
import sys
from unittest.mock import mock_open, patch

# Add scripts directory to path so we can import install_helpers
SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))
sys.path.insert(0, SCRIPTS_DIR)

from install_helpers import read_env_key, update_env_key  # noqa: E402

# Locate the installation script relative to this test file
SCRIPT_PATH = os.path.abspath(
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "install_prod.sh")
)


def test_update_env_key():
    """Verify that update_env_key correctly replaces LOCAL_API_KEY in a .env file."""
    # Test cases: (original_content, api_key_value, expected_new_content)
    test_cases = [
        (
            "LOCAL_API_KEY=oldkey\nOTHER_VAR=val",  # pragma: allowlist secret
            "newkey",
            'LOCAL_API_KEY="newkey"\nOTHER_VAR=val',  # pragma: allowlist secret
        ),
        (
            "  export LOCAL_API_KEY=foo\n",  # pragma: allowlist secret
            'bar\\baz"quote',
            '  export LOCAL_API_KEY="bar\\\\baz\\"quote"\n',  # pragma: allowlist secret
        ),
        (
            "# LOCAL_API_KEY is not active\nLOCAL_API_KEY = something\n",
            "new#key",
            '# LOCAL_API_KEY is not active\nLOCAL_API_KEY="new#key"\n',  # pragma: allowlist secret
        ),
        (
            "OTHER_VAR=value\nANOTHER=foo",
            "newkey",
            "OTHER_VAR=value\nANOTHER=foo",
        ),
    ]

    for original, key_val, expected in test_cases:
        m_open = mock_open(read_data=original)

        with (
            patch("builtins.open", m_open),
            patch("sys.argv", ["python3", "dummy_env_file"]),
            patch.dict(os.environ, {"LOCAL_API_KEY_VALUE": key_val}),
        ):
            update_env_key("dummy_env_file", key_val)

            # Reconstruct the written data from all calls to write()
            written_data = "".join(call.args[0] for call in m_open().write.call_args_list)
            assert written_data == expected, (
                f"for key={key_val!r}:\n  expected: {expected!r}\n  got:      {written_data!r}"
            )


def test_read_env_key_comment_stripping():
    """Verify that read_env_key correctly handles keys with '#' in the value vs comments."""
    # Test cases: (file_content, expected_parsed_key)
    test_cases = [
        ("LOCAL_API_KEY=my#secretkey", "my#secretkey"),  # pragma: allowlist secret
        ("LOCAL_API_KEY=mysecretkey # some comment", "mysecretkey"),  # pragma: allowlist secret
        ("LOCAL_API_KEY=mysecretkey #some comment", "mysecretkey"),  # pragma: allowlist secret
        ('LOCAL_API_KEY="my#secretkey"', "my#secretkey"),  # pragma: allowlist secret
        ("LOCAL_API_KEY='my#secretkey'", "my#secretkey"),  # pragma: allowlist secret
        (
            "LOCAL_API_KEY=my#secretkey#with#many#hashes",
            "my#secretkey#with#many#hashes",
        ),  # pragma: allowlist secret
        ("LOCAL_API_KEY=my#secretkey # comment here", "my#secretkey"),  # pragma: allowlist secret
        ("export LOCAL_API_KEY=some_key", "some_key"),  # pragma: allowlist secret
        ("  LOCAL_API_KEY  =  another_key  ", "another_key"),
        ('LOCAL_API_KEY="key_with_\\"_quotes"', 'key_with_"_quotes'),  # pragma: allowlist secret
        ("LOCAL_API_KEY='key_with_\\'_quotes'", "key_with_'_quotes"),  # pragma: allowlist secret
    ]

    for file_content, expected_key in test_cases:
        m_open = mock_open(read_data=file_content)

        with (
            patch("builtins.open", m_open),
        ):
            result = read_env_key("dummy_env_file")
            assert result == expected_key, (
                f"for content={file_content!r}:\n"
                f"  expected: {expected_key!r}\n"
                f"  got:      {result!r}"
            )


def test_write_env_key_escaping(tmp_path):
    """Verify that _write_env_key correctly escapes backslashes and double quotes
    by extracting and executing the actual bash function from install_prod.sh."""
    # Extract the _write_env_key function definition from the script
    with open(SCRIPT_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # Match _write_env_key function block robustly using regex
    match = re.search(r"^\s*_write_env_key\s*\(\)\s*\{[\s\S]*?\n\}", content, re.MULTILINE)
    assert match is not None, "_write_env_key() function block not found in install_prod.sh"
    func_body = match.group(0)

    # Write the extracted function to a temp file for sourcing
    func_file = tmp_path / "_write_env_key.sh"
    func_file.write_text(func_body)

    test_cases = [
        ("simplekey", 'LOCAL_API_KEY="simplekey"\n'),  # pragma: allowlist secret
        (
            "key\\with\\backslashes",
            'LOCAL_API_KEY="key\\\\with\\\\backslashes"\n',  # pragma: allowlist secret
        ),  # pragma: allowlist secret
        ('key"with"quotes', 'LOCAL_API_KEY="key\\"with\\"quotes"\n'),  # pragma: allowlist secret
        ('key\\with"both', 'LOCAL_API_KEY="key\\\\with\\"both"\n'),  # pragma: allowlist secret
        (
            "key\\\\double\\\\backslashes",
            'LOCAL_API_KEY="key\\\\\\\\double\\\\\\\\backslashes"\n',  # pragma: allowlist secret
        ),  # pragma: allowlist secret
    ]

    for input_key, expected in test_cases:
        result = subprocess.run(
            ["bash", "-c", f'source "{func_file}"; _write_env_key'],
            env={**os.environ, "LOCAL_API_KEY": input_key},
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"bash _write_env_key failed: {result.stderr}"
        assert result.stdout == expected, (
            f"for key={input_key!r}:\n  expected: {expected!r}\n  got:      {result.stdout!r}"
        )


def test_no_redundant_chmod():
    """Verify that redundant chmod calls on the .env file have been removed
    to prevent regressions."""
    with open(SCRIPT_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # Find all occurrences of chmod 600 targeting the .env file
    chmod_calls = __import__("re").findall(r"chmod\s+600\s+.*\.env", content)
    assert len(chmod_calls) == 1, f"Expected exactly 1 chmod 600 call on .env, found: {chmod_calls}"


def test_cli_dispatch_insufficient_args(capsys):
    import pytest
    from install_helpers import _cli_dispatch

    with patch("sys.argv", ["install_helpers.py"]):
        with pytest.raises(SystemExit) as excinfo:
            _cli_dispatch()
        assert excinfo.value.code == 1
        captured = capsys.readouterr()
        assert "Usage: install_helpers.py <command> [args]" in captured.err


def test_cli_dispatch_unknown_command(capsys):
    import pytest
    from install_helpers import _cli_dispatch

    with patch("sys.argv", ["install_helpers.py", "invalid_cmd"]):
        with pytest.raises(SystemExit) as excinfo:
            _cli_dispatch()
        assert excinfo.value.code == 1
        captured = capsys.readouterr()
        assert "Unknown command: invalid_cmd" in captured.err


def test_cli_update_env_key_insufficient_args(capsys):
    import pytest
    from install_helpers import _cli_dispatch

    with patch("sys.argv", ["install_helpers.py", "update_env_key"]):
        with pytest.raises(SystemExit) as excinfo:
            _cli_dispatch()
        assert excinfo.value.code == 1
        captured = capsys.readouterr()
        assert "Usage: install_helpers.py update_env_key <env_file>" in captured.err


def test_cli_update_env_key_missing_env_var(capsys):
    import pytest
    from install_helpers import _cli_dispatch

    with patch("sys.argv", ["install_helpers.py", "update_env_key", "dummy_file"]):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(SystemExit) as excinfo:
                _cli_dispatch()
            assert excinfo.value.code == 1
            captured = capsys.readouterr()
            assert "Error: LOCAL_API_KEY_VALUE environment variable not set" in captured.err


def test_cli_update_env_key_success():
    from install_helpers import _cli_dispatch

    with patch("sys.argv", ["install_helpers.py", "update_env_key", "dummy_file"]):
        with patch.dict(os.environ, {"LOCAL_API_KEY_VALUE": "mykey"}):  # pragma: allowlist secret
            with patch("install_helpers.update_env_key") as mock_update:
                _cli_dispatch()
                mock_update.assert_called_once_with(
                    "dummy_file", "mykey"
                )  # pragma: allowlist secret


def test_cli_read_env_key_insufficient_args(capsys):
    import pytest
    from install_helpers import _cli_dispatch

    with patch("sys.argv", ["install_helpers.py", "read_env_key"]):
        with pytest.raises(SystemExit) as excinfo:
            _cli_dispatch()
        assert excinfo.value.code == 1
        captured = capsys.readouterr()
        assert "Usage: install_helpers.py read_env_key <env_file>" in captured.err


def test_cli_read_env_key_success(capsys):
    from install_helpers import _cli_dispatch

    with patch("sys.argv", ["install_helpers.py", "read_env_key", "dummy_file"]):
        with patch(
            "install_helpers.read_env_key", return_value="mykey"
        ) as mock_read:  # pragma: allowlist secret
            _cli_dispatch()
            captured = capsys.readouterr()
            assert mock_read.called
            assert captured.out == "mykey\n"  # pragma: allowlist secret
