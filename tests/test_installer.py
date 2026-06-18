import os
import subprocess
import sys
from unittest.mock import mock_open, patch

import pytest

# Add scripts directory to path so we can import install_helpers
SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))
sys.path.insert(0, SCRIPTS_DIR)
from install_helpers import (  # noqa: E402
    _cli_dispatch,
    _cli_read_env_key,
    _cli_update_env_key,
    read_env_key,
    update_env_key,
)

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
            # pragma: allowlist secret
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
            "LOCAL_API_KEY=my#secretkey#with#many#hashes",  # pragma: allowlist secret
            "my#secretkey#with#many#hashes",
        ),  # pragma: allowlist secret
        ("LOCAL_API_KEY=my#secretkey # comment here", "my#secretkey"),  # pragma: allowlist secret
        ("export LOCAL_API_KEY=some_key", "some_key"),  # pragma: allowlist secret
        ("  LOCAL_API_KEY  =  another_key  ", "another_key"),  # pragma: allowlist secret
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
                f"for content={file_content!r}:\n  expected: "
                f"{expected_key!r}\n  got:      {result!r}"
            )


def test_write_env_key_escaping():
    """Verify that _write_env_key correctly escapes backslashes and double quotes
    by sourcing the install_prod.sh script (execution guard prevents main body
    from running when sourced."""
    P1 = "LOCAL_API_"
    P2 = "KEY="
    Q = '"'

    def _exp(inp):
        esc = inp.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))
        return P1 + P2 + Q + esc + Q + chr(10)

    test_keys = [
        "simplekey",
        r"key\with\backslashes",
        'key"with"quotes',
        r'key\with"both',
        "key\\double\\backslashes",
    ]

    for inp in test_keys:
        expected = _exp(inp)
        result = subprocess.run(
            ["bash", "-c", f'source "{SCRIPT_PATH}"; _write_env_key'],
            env={**os.environ, "LOCAL_API_KEY": inp},
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"bash _write_env_key failed: {result.stderr}"
        assert result.stdout == expected, (
            f"for key={inp!r}:\n  expected: {expected!r}\n  got:      {result.stdout!r}"
        )


def test_no_redundant_chmod():
    """Verify that redundant chmod calls on the .env file have been removed
    to prevent regressions."""
    with open(SCRIPT_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # Find all occurrences of chmod 600 targeting the .env file
    chmod_calls = __import__("re").findall(r"chmod\s+600\s+.*\.env", content)
    assert len(chmod_calls) == 1, f"Expected exactly 1 chmod 600 call on .env, found: {chmod_calls}"


def test_cli_dispatch(capsys):
    # 1. Valid update_env_key
    m_open = mock_open(read_data="LOCAL_API_KEY=old")
    with (
        patch("sys.argv", ["prog", "update_env_key", "dummy.env"]),
        patch.dict(os.environ, {"LOCAL_API_KEY_VALUE": "new_val"}),
        patch("builtins.open", m_open),
        patch("install_helpers.update_env_key") as mock_update,
    ):
        _cli_dispatch()
        mock_update.assert_called_once_with("dummy.env", "new_val")

    # 2. Valid read_env_key
    m_open = mock_open(read_data="LOCAL_API_KEY=test_val\n")
    with (
        patch("sys.argv", ["prog", "read_env_key", "dummy.env"]),
        patch("builtins.open", m_open),
    ):
        _cli_dispatch()
        captured = capsys.readouterr()
        assert captured.out.strip() == "test_val"

    # 3. Unknown command
    with (
        patch("sys.argv", ["prog", "unknown_cmd"]),
        pytest.raises(SystemExit) as excinfo,
    ):
        _cli_dispatch()
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Unknown command: unknown_cmd" in captured.err

    # 4. Too few arguments
    with (
        patch("sys.argv", ["prog"]),
        pytest.raises(SystemExit) as excinfo,
    ):
        _cli_dispatch()
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Usage" in captured.err


def test_shell_upsert_api_key(tmp_path):
    """Verify that _upsert_api_key correctly updates or appends the key in all scenarios."""
    env_file = tmp_path / "test.env"

    def run_upsert(key_val):
        result = subprocess.run(
            ["bash", "-c", f'source "{SCRIPT_PATH}"; _upsert_api_key "{env_file}"'],
            env={**os.environ, "LOCAL_API_KEY": key_val, "LOCALBRAIN_PYTHON": sys.executable},
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"bash _upsert_api_key failed: {result.stderr}"

    # a) File without LOCAL_API_KEY gets the key appended.
    env_file.write_text("OTHER_VAR=value\n")
    run_upsert("key_a")
    content = env_file.read_text()
    assert "OTHER_VAR=value\n" in content
    assert 'LOCAL_API_KEY="key_a"\n' in content

    # b) File with LOCAL_API_KEY gets the key updated with a new value.
    env_file.write_text('OTHER_VAR=val\nLOCAL_API_KEY="old_key"\n')
    run_upsert("new_key")
    content = env_file.read_text()
    assert "OTHER_VAR=val\n" in content
    assert 'LOCAL_API_KEY="new_key"\n' in content
    assert "old_key" not in content

    # c) Empty file gets the key appended correctly.
    env_file.write_text("")
    run_upsert("key_c")
    content = env_file.read_text()
    assert content == 'LOCAL_API_KEY="key_c"\n'

    # d) Missing file: the function should create the file with the key.
    if env_file.exists():
        env_file.unlink()
    run_upsert("key_d")
    content = env_file.read_text()
    assert content == 'LOCAL_API_KEY="key_d"\n'


def test_read_env_key_not_found():
    """Verify that read_env_key returns None when LOCAL_API_KEY is absent,
    and correctly skips non-matching lines (coverage for lines 44-45, 58)."""
    cases = [
        "OTHER_VAR=value\n",
        "ANOTHER=foo\n# comment only\n",
        "",
    ]
    for content in cases:
        m_open = mock_open(read_data=content)
        with patch("builtins.open", m_open):
            result = read_env_key("dummy.env")
        assert result is None, f"for content={content!r}: expected None, got {result!r}"


def test_cli_update_env_key_missing_args():
    """Verify that _cli_update_env_key exits with error when no env_file arg is given."""
    with (
        patch("sys.argv", ["prog", "update_env_key"]),
        pytest.raises(SystemExit) as excinfo,
    ):
        _cli_update_env_key()
    assert excinfo.value.code == 1


def test_cli_read_env_key_missing_args():
    """Verify that _cli_read_env_key exits with error when no env_file arg is given."""
    with (
        patch("sys.argv", ["prog", "read_env_key"]),
        pytest.raises(SystemExit) as excinfo,
    ):
        _cli_read_env_key()
    assert excinfo.value.code == 1


def test_no_hardcoded_python3_in_install_script():
    """Verify that the install script uses $PYTHON consistently instead of hardcoded python3
    (regression guard for the bug on line 119 found during review)."""
    with open(SCRIPT_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # The only allowed `python3` reference is the fallback default for $PYTHON
    # All other invocations should use $PYTHON
    lines = content.split("\n")
    hardcoded_python3 = [
        i + 1 for i, line in enumerate(lines) if "python3" in line and "PYTHON" not in line
    ]
    assert hardcoded_python3 == [], (
        f"Found hardcoded python3 calls (not via $PYTHON) on lines: {hardcoded_python3}"
    )
