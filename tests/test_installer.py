import os
import re
import subprocess
import sys
from unittest.mock import mock_open, patch

# Locate the installation script relative to this test file
SCRIPT_PATH = os.path.abspath(
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "install_prod.sh")
)

# Add scripts directory to sys.path to import install_helpers
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))
import install_helpers  # noqa: E402


def test_update_env_key():
    """Verify that update_env_key correctly replaces LOCAL_API_KEY in a .env file."""
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
        (
            "OTHER_VAR=value\nANOTHER=foo",
            "newkey",
            "OTHER_VAR=value\nANOTHER=foo",
        ),
    ]

    for original, key_val, expected in test_cases:
        m_open = mock_open(read_data=original)

        with patch("builtins.open", m_open):
            install_helpers.update_env_key("dummy_env_file", key_val)

            # Reconstruct the written data from all calls to write()
            written_data = "".join(call.args[0] for call in m_open().write.call_args_list)
            assert written_data == expected


def test_read_env_key_comment_stripping():
    """Verify that the unquoted value comment-stripping regex correctly

    handles keys with '#' in the value vs comments.
    """
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

        with patch("builtins.open", m_open):
            val = install_helpers.read_env_key("dummy_env_file")
            assert val == expected_key


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
        ("simplekey", 'LOCAL_API_KEY="simplekey"\n'),
        ("key\\with\\backslashes", 'LOCAL_API_KEY="key\\\\with\\\\backslashes"\n'),
        ('key"with"quotes', 'LOCAL_API_KEY="key\\"with\\"quotes"\n'),
        ('key\\with"both', 'LOCAL_API_KEY="key\\\\with\\"both"\n'),
        ("key\\\\double\\\\backslashes", 'LOCAL_API_KEY="key\\\\\\\\double\\\\\\\\backslashes"\n'),
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
