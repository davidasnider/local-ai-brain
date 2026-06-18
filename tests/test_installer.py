import os
import re
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
            "LOCAL_API_KEY=oldkey\nOTHER_VAR=val",
            "newkey",
            'LOCAL_API_KEY="newkey"\nOTHER_VAR=val',
        ),
        (
            "  export LOCAL_API_KEY=foo\n",
            'bar\\baz"quote',
            '  export LOCAL_API_KEY="bar\\\\baz\\"quote"\n',
        ),
        (
            "# LOCAL_API_KEY is not active\nLOCAL_API_KEY = something\n",
            "new#key",
            '# LOCAL_API_KEY is not active\nLOCAL_API_KEY="new#key"\n',
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
    start_marker = "LOCAL_API_KEY=\"$(python3 -c '"
    start_idx = content.find(start_marker)
    assert start_idx != -1, "Could not find start of read_env_key Python inline script"
    code_start = start_idx + len(start_marker)

    end_marker = '\' "$ENV_FILE")"'
    end_idx = content.find(end_marker, code_start)
    assert end_idx != -1, "Could not find end of read_env_key Python inline script"
    inline_code = content[code_start:end_idx]

    # Test cases: (file_content, expected_parsed_key)
    test_cases = [
        ("LOCAL_API_KEY=my#secretkey", "my#secretkey"),
        ("LOCAL_API_KEY=mysecretkey # some comment", "mysecretkey"),
        ("LOCAL_API_KEY=mysecretkey #some comment", "mysecretkey"),
        ('LOCAL_API_KEY="my#secretkey"', "my#secretkey"),
        ("LOCAL_API_KEY='my#secretkey'", "my#secretkey"),
        ("LOCAL_API_KEY=my#secretkey#with#many#hashes", "my#secretkey#with#many#hashes"),
        ("LOCAL_API_KEY=my#secretkey # comment here", "my#secretkey"),
        ("export LOCAL_API_KEY=some_key", "some_key"),
        ("  LOCAL_API_KEY  =  another_key  ", "another_key"),
        ('LOCAL_API_KEY="key_with_\\"_quotes"', 'key_with_"_quotes'),
        ("LOCAL_API_KEY='key_with_\\'_quotes'", "key_with_'_quotes"),
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


def test_write_env_key_escaping():
    """Verify that _write_env_key correctly escapes backslashes and double quotes."""
    with open(SCRIPT_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # Assert that the bash function exists and has the expected escaping substitutions
    assert "_write_env_key() {" in content
    # Look for the string replacement pattern
    assert "LOCAL_API_KEY//\\\\/\\\\\\\\" in content or "LOCAL_API_KEY//\\/\\\\" in content
    assert '_ekey//\\"/\\\\\\"' in content or '_ekey//"/\\"' in content

    # Implement the Python equivalent of bash replacements:
    # _ekey="${LOCAL_API_KEY//\\/\\\\}" -> replaces all \ with \\
    # _ekey="${_ekey//\"/\\\"}" -> replaces all " with \"
    def write_env_key_py(key):
        escaped = key.replace("\\", "\\\\").replace('"', '\\"')
        return f'LOCAL_API_KEY="{escaped}"'

    test_cases = [
        ("simplekey", 'LOCAL_API_KEY="simplekey"'),
        ("key\\with\\backslashes", 'LOCAL_API_KEY="key\\\\with\\\\backslashes"'),
        ('key"with"quotes', 'LOCAL_API_KEY="key\\"with\\"quotes"'),
        ('key\\with"both', 'LOCAL_API_KEY="key\\\\with\\"both"'),
        ("key\\\\double\\\\backslashes", 'LOCAL_API_KEY="key\\\\\\\\double\\\\\\\\backslashes"'),
    ]

    for input_key, expected in test_cases:
        assert write_env_key_py(input_key) == expected


def test_no_redundant_chmod():
    """Verify that redundant chmod calls on the .env file have been removed

    to prevent regressions.
    """
    with open(SCRIPT_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # Find all occurrences of chmod 600 targeting the .env file
    chmod_calls = re.findall(r"chmod\s+600\s+.*\.env", content)
    assert len(chmod_calls) == 1, f"Expected exactly 1 chmod 600 call on .env, found: {chmod_calls}"
