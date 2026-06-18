import os
import re
import subprocess
from unittest.mock import mock_open, patch

# Locate the installation script relative to this test file
SCRIPT_PATH = os.path.abspath(
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "install_prod.sh")
)


def test_update_env_key():
    """Verify that update_env_key correctly replaces LOCAL_API_KEY in a .env file."""
    with open(SCRIPT_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # Extract the inline python code for update_env_key
    # Starts with: LOCAL_API_KEY_VALUE="$LOCAL_API_KEY" python3 -c '
    # Ends with: ' "$env_file"
    start_marker = 'LOCAL_API_KEY_VALUE="$LOCAL_API_KEY" python3 -c \''
    start_idx = content.find(start_marker)
    assert start_idx != -1, "Could not find start of update_env_key Python inline script"
    code_start = start_idx + len(start_marker)

    end_marker = '\' "$env_file"'
    end_idx = content.find(end_marker, code_start)
    assert end_idx != -1, "Could not find end of update_env_key Python inline script"
    inline_code = content[code_start:end_idx]

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

        # Patch sys.argv, os.environ, and builtins.open to run the script in isolation
        with (
            patch("sys.argv", ["python3", "dummy_env_file"]),
            patch.dict(os.environ, {"LOCAL_API_KEY_VALUE": key_val}),
            patch("builtins.open", m_open),
        ):
            local_vars = {}
            exec(inline_code, local_vars)

            # Reconstruct the written data from all calls to write()
            written_data = "".join(call.args[0] for call in m_open().write.call_args_list)
            assert written_data == expected


def test_read_env_key_comment_stripping():
    """Verify that the unquoted value comment-stripping regex correctly

    handles keys with '#' in the value vs comments.
    """
    with open(SCRIPT_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # Extract the inline python code for reading LOCAL_API_KEY
    # Starts with: LOCAL_API_KEY="$(python3 -c '
    # Ends with: ' "$ENV_FILE")"
    start_marker = "LOCAL_API_KEY=\"$(python3 -c '"  # pragma: allowlist secret
    start_idx = content.find(start_marker)
    assert start_idx != -1, "Could not find start of read_env_key Python inline script"
    code_start = start_idx + len(start_marker)

    end_marker = '\' "$ENV_FILE")"'
    end_idx = content.find(end_marker, code_start)
    assert end_idx != -1, "Could not find end of read_env_key Python inline script"
    inline_code = content[code_start:end_idx]

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

        # Patch sys.argv, builtins.open, and print to run and inspect execution
        with (
            patch("sys.argv", ["python3", "dummy_env_file"]),
            patch("builtins.open", m_open),
            patch("builtins.print") as mock_print,
        ):
            local_vars = {}
            exec(inline_code, local_vars)

            if expected_key is None:
                mock_print.assert_not_called()
            else:
                mock_print.assert_called_once_with(expected_key)


def test_write_env_key_escaping(tmp_path):
    """Verify that _write_env_key correctly escapes backslashes and double quotes
    by extracting and executing the actual bash function from install_prod.sh."""
    # Extract the _write_env_key function definition from the script
    with open(SCRIPT_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    func_start = content.find("_write_env_key() {")
    assert func_start != -1, "_write_env_key() not found in install_prod.sh"

    # Find the closing brace that comes after the printf line
    printf_idx = content.find("printf", func_start)
    assert printf_idx != -1, "printf not found in _write_env_key"
    closing_brace_idx = content.find("}", printf_idx)
    assert closing_brace_idx != -1, "closing brace not found after printf in _write_env_key"
    func_end = closing_brace_idx + 1

    func_body = content[func_start:func_end]

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

    to prevent regressions.
    """
    with open(SCRIPT_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # Find all occurrences of chmod 600 targeting the .env file
    chmod_calls = re.findall(r"chmod\s+600\s+.*\.env", content)
    assert len(chmod_calls) == 1, f"Expected exactly 1 chmod 600 call on .env, found: {chmod_calls}"
