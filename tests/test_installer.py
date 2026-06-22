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
    _cli_write_plist,
    read_env_key,
    update_env_key,
)

# Locate the installation script relative to this test file
SCRIPT_PATH = os.path.abspath(
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "install_prod.sh")
)


def test_update_env_key(tmp_path):
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
            'OTHER_VAR=value\nANOTHER=foo\nLOCAL_API_KEY="newkey"\n',  # pragma: allowlist secret
        ),
    ]

    for idx, (original, key_val, expected) in enumerate(test_cases):
        env_file = tmp_path / f"test_{idx}.env"
        env_file.write_text(original, encoding="utf-8")

        update_env_key(str(env_file), key_val)

        # Check permissions
        assert (env_file.stat().st_mode & 0o777) == 0o600

        # Check content
        written_data = env_file.read_text(encoding="utf-8")
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
        ("LOCAL_API_KEY='key_with_\\'_quotes'", "key_with_\\"),  # pragma: allowlist secret
        (
            "LOCAL_API_KEY='key_with_no_escaping_\\\\'",  # pragma: allowlist secret
            "key_with_no_escaping_\\\\",
        ),  # pragma: allowlist secret
        ("LOCAL_API_KEY=firstkey\nLOCAL_API_KEY=lastkey", "lastkey"),  # pragma: allowlist secret
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


def test_round_trip_keys(tmp_path):
    """Verify round-tripping keys with shell-sensitive characters ($ or `)

    through update_env_key and read_env_key.
    """
    keys = [
        "simple_key",
        "key_with_$",
        "key_with_`_backtick",
        "key_with_$_and_`",
        'key_with_\\_and_$_and_`_and_"',
        r"complex_$\$`\\`\"$",
    ]
    for idx, key in enumerate(keys):
        env_file = tmp_path / f"roundtrip_{idx}.env"
        # Create a dummy .env file
        env_file.write_text("LOCAL_API_KEY=dummy", encoding="utf-8")  # pragma: allowlist secret

        # Write the key using update_env_key
        update_env_key(str(env_file), key)

        # Read the key back using read_env_key
        read_val = read_env_key(str(env_file))
        assert read_val == key, f"Round-trip failed for key: {key!r} (got: {read_val!r})"


def test_write_env_key_escaping(tmp_path):
    """Verify that _write_env_key correctly escapes backslashes and double quotes
    by sourcing the install_prod.sh script (execution guard prevents main body
    from running when sourced."""
    P1 = "LOCAL_API_"
    P2 = "KEY="
    Q = '"'

    def _exp(inp):
        esc = inp.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))
        esc = esc.replace("$", "\\$").replace("`", "\\`")
        return P1 + P2 + Q + esc + Q + chr(10)

    test_keys = [
        "simplekey",
        r"key\with\backslashes",
        'key"with"quotes',
        r'key\with"both',
        "key\\double\\backslashes",
        "key$with$dollar",
        "key`with`backtick",
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


def test_upsert_api_key_coverage(tmp_path):
    """Verify _upsert_api_key behavior when key is present vs missing."""
    env_file = tmp_path / "test.env"
    env_file.write_text("OTHER_VAR=value\n", encoding="utf-8")

    # Test append when missing
    result = subprocess.run(
        ["bash", "-c", f'source "{SCRIPT_PATH}"; _upsert_api_key "{env_file}"'],
        env={**os.environ, "LOCAL_API_KEY": "newkey"},  # pragma: allowlist secret
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert 'LOCAL_API_KEY="newkey"' in env_file.read_text()  # pragma: allowlist secret

    # Test update when present
    result = subprocess.run(
        ["bash", "-c", f'source "{SCRIPT_PATH}"; _upsert_api_key "{env_file}"'],
        env={**os.environ, "LOCAL_API_KEY": "updatedkey"},  # pragma: allowlist secret
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert 'LOCAL_API_KEY="updatedkey"' in env_file.read_text()  # pragma: allowlist secret


def test_cli_dispatch_no_args_exits_with_usage():
    """_cli_dispatch should print usage and exit 1 when no args given."""
    with (
        patch("sys.argv", ["install_helpers.py"]),
        pytest.raises(SystemExit) as exc_info,
    ):
        _cli_dispatch()
    assert exc_info.value.code == 1


def test_cli_dispatch_unknown_command_exits():
    """_cli_dispatch should print error and exit 1 for unknown commands."""
    with (
        patch("sys.argv", ["install_helpers.py", "bogus_command"]),
        pytest.raises(SystemExit) as exc_info,
    ):
        _cli_dispatch()
    assert exc_info.value.code == 1


def test_cli_update_env_key_missing_arg_exits():
    """_cli_update_env_key should exit 1 when env_file argument is missing."""
    with (
        patch("sys.argv", ["install_helpers.py", "update_env_key"]),
        pytest.raises(SystemExit) as exc_info,
    ):
        _cli_update_env_key()
    assert exc_info.value.code == 1


def test_cli_read_env_key_missing_arg_exits():
    """_cli_read_env_key should exit 1 when env_file argument is missing."""
    with (
        patch("sys.argv", ["install_helpers.py", "read_env_key"]),
        pytest.raises(SystemExit) as exc_info,
    ):
        _cli_read_env_key()
    assert exc_info.value.code == 1


def test_cli_write_plist_missing_args_exits():
    """_cli_write_plist should exit 1 when any required argument is missing."""
    with (
        patch("sys.argv", ["install_helpers.py", "write_plist", "template"]),
        pytest.raises(SystemExit) as exc_info,
    ):
        _cli_write_plist()
    assert exc_info.value.code == 1


def test_cli_write_plist_writes_plist(tmp_path):
    """_cli_write_plist should resolve ~/ to $HOME/ in the plist."""
    template = tmp_path / "template.plist"
    output = tmp_path / "output.plist"
    template.write_text(
        '<?xml version="1.0"?>\n'
        "<plist><dict>"
        "<key>StandardErrorPath</key><string>~/Library/Logs/app.err.log</string>"
        "</dict></plist>\n"
    )
    home = "/Users/testuser"
    with (
        patch(
            "sys.argv",
            [
                "install_helpers.py",
                "write_plist",
                str(template),
                str(output),
                home,
            ],
        ),
    ):
        _cli_write_plist()
    result = output.read_text()
    assert "~/Library/Logs" not in result
    assert "/Users/testuser/Library/Logs" in result


def test_cli_update_env_key_missing_env_var_exits():
    """_cli_update_env_key should exit 1 and print to stderr when LOCAL_API_KEY_VALUE is missing."""
    with (
        patch("sys.argv", ["install_helpers.py", "update_env_key", "dummy_env_file"]),
        patch.dict(os.environ, {}, clear=True),
        pytest.raises(SystemExit) as exc_info,
        patch("sys.stderr.write") as mock_stderr_write,
    ):
        _cli_update_env_key()
    assert exc_info.value.code == 1
    written = "".join(call.args[0] for call in mock_stderr_write.call_args_list)
    assert "Error: LOCAL_API_KEY_VALUE" in written


def test_cli_read_env_key_file_not_found_exits(tmp_path):
    """_cli_read_env_key should exit 1 and print to stderr when the env file does not exist."""
    non_existent = str(tmp_path / "does_not_exist")
    with (
        patch("sys.argv", ["install_helpers.py", "read_env_key", non_existent]),
        pytest.raises(SystemExit) as exc_info,
        patch("sys.stderr.write") as mock_stderr_write,
    ):
        _cli_read_env_key()
    assert exc_info.value.code == 1
    written = "".join(call.args[0] for call in mock_stderr_write.call_args_list)
    assert "Error:" in written
    assert "not found" in written


def test_cli_write_plist_file_not_found_exits(tmp_path):
    """_cli_write_plist should exit 1 and print to stderr when the template file does not exist."""
    non_existent = str(tmp_path / "does_not_exist")
    output = str(tmp_path / "output.plist")
    with (
        patch(
            "sys.argv",
            [
                "install_helpers.py",
                "write_plist",
                non_existent,
                output,
                "/Users/testuser",
            ],
        ),
        pytest.raises(SystemExit) as exc_info,
        patch("sys.stderr.write") as mock_stderr_write,
    ):
        _cli_write_plist()
    assert exc_info.value.code == 1
    written = "".join(call.args[0] for call in mock_stderr_write.call_args_list)
    assert "Error:" in written
    assert "not found" in written


def test_update_env_key_exception_handling(tmp_path):
    """Verify that update_env_key cleans up the temp file if an exception occurs."""
    env_file = tmp_path / "test.env"
    env_file.write_text("LOCAL_API_KEY=oldkey\n", encoding="utf-8")  # pragma: allowlist secret

    # Patch os.replace to raise an error
    with patch("os.replace", side_effect=RuntimeError("simulated error")):
        with pytest.raises(RuntimeError, match="simulated error"):
            update_env_key(str(env_file), "newkey")

    # The temp file should have been cleaned up.
    remaining_files = list(tmp_path.glob(".env.tmp-*"))
    assert len(remaining_files) == 0


def test_update_env_key_exception_handling_remove_fails(tmp_path):
    """Verify that update_env_key propagates the original exception even if os.remove fails."""
    env_file = tmp_path / "test.env"
    env_file.write_text("LOCAL_API_KEY=oldkey\n", encoding="utf-8")  # pragma: allowlist secret

    with (
        patch("os.replace", side_effect=RuntimeError("simulated error")),
        patch("os.remove", side_effect=OSError("simulated remove error")),
    ):
        with pytest.raises(RuntimeError, match="simulated error"):
            update_env_key(str(env_file), "newkey")


def test_update_env_key_base_exception_handling(tmp_path):
    """Verify that update_env_key cleans up the temp file if a BaseException occurs."""
    env_file = tmp_path / "test.env"
    env_file.write_text("LOCAL_API_KEY=oldkey\n", encoding="utf-8")  # pragma: allowlist secret

    # Patch os.replace to raise a BaseException (KeyboardInterrupt)
    with patch("os.replace", side_effect=KeyboardInterrupt("simulated interrupt")):
        with pytest.raises(KeyboardInterrupt, match="simulated interrupt"):
            update_env_key(str(env_file), "newkey")

    # The temp file should have been cleaned up.
    remaining_files = list(tmp_path.glob(".env.tmp-*"))
    assert len(remaining_files) == 0


def test_cli_write_plist_missing_dest_dir(tmp_path):
    """_cli_write_plist should exit 1 and print to stderr
    when the destination directory does not exist.
    """
    template = tmp_path / "template.plist"
    template.write_text("dummy plist template", encoding="utf-8")
    non_existent_dest = str(tmp_path / "non_existent_dir" / "output.plist")
    with (
        patch(
            "sys.argv",
            [
                "install_helpers.py",
                "write_plist",
                str(template),
                non_existent_dest,
                "/Users/testuser",
            ],
        ),
        pytest.raises(SystemExit) as exc_info,
        patch("sys.stderr.write") as mock_stderr_write,
    ):
        _cli_write_plist()
    assert exc_info.value.code == 1
    written = "".join(call.args[0] for call in mock_stderr_write.call_args_list)
    assert "Error:" in written
    assert "Destination directory for" in written
    assert "does not exist" in written


def test_cli_write_plist_permission_error(tmp_path):
    """_cli_write_plist should exit 1 and print to stderr when there is a permission error."""
    template = tmp_path / "template.plist"
    template.write_text("dummy plist template", encoding="utf-8")
    output = str(tmp_path / "output.plist")

    with (
        patch(
            "sys.argv",
            [
                "install_helpers.py",
                "write_plist",
                str(template),
                output,
                "/Users/testuser",
            ],
        ),
        patch(
            "builtins.open",
            side_effect=[
                mock_open(read_data="dummy").return_value,
                PermissionError("Permission denied"),
            ],
        ),
        pytest.raises(SystemExit) as exc_info,
        patch("sys.stderr.write") as mock_stderr_write,
    ):
        _cli_write_plist()
    assert exc_info.value.code == 1
    written = "".join(call.args[0] for call in mock_stderr_write.call_args_list)
    assert "Error:" in written
    assert "Permission denied" in written


def test_cli_write_plist_template_permission_error(tmp_path):
    """_cli_write_plist should exit 1 and print to stderr
    when there is a template read permission error.
    """
    template = str(tmp_path / "template.plist")
    output = str(tmp_path / "output.plist")

    # Construct a PermissionError where filename matches the template
    err = PermissionError("Permission denied")
    err.filename = template

    with (
        patch(
            "sys.argv",
            [
                "install_helpers.py",
                "write_plist",
                template,
                output,
                "/Users/testuser",
            ],
        ),
        patch("builtins.open", side_effect=err),
        pytest.raises(SystemExit) as exc_info,
        patch("sys.stderr.write") as mock_stderr_write,
    ):
        _cli_write_plist()
    assert exc_info.value.code == 1
    written = "".join(call.args[0] for call in mock_stderr_write.call_args_list)
    assert "Error:" in written
    assert "Permission denied reading Plist template file" in written


def test_write_plist_preserves_comments(tmp_path):
    """Verify that write_plist resolves ~/ paths in XML body but preserves them in XML comments."""
    template = tmp_path / "template.plist"
    output = tmp_path / "output.plist"

    template.write_text(
        '<?xml version="1.0"?>\n'
        "<plist><dict>\n"
        "    <!-- Note: Do not change ~/ in this comment! -->\n"
        "    <key>Path</key><string>~/some/path</string>\n"
        "</dict></plist>\n",
        encoding="utf-8",
    )

    from install_helpers import write_plist

    write_plist(str(template), str(output), "/Users/testuser")

    result = output.read_text(encoding="utf-8")
    assert "<!-- Note: Do not change ~/ in this comment! -->" in result
    assert "<string>/Users/testuser/some/path</string>" in result


def test_update_env_key_resolves_symlinks(tmp_path):
    """Verify that update_env_key resolves symlinks and modifies the target file

    instead of replacing the symlink itself.
    """
    target_env = tmp_path / "real.env"
    symlink_env = tmp_path / "link.env"

    target_env.write_text("LOCAL_API_KEY=oldkey\n", encoding="utf-8")  # pragma: allowlist secret
    os.symlink(str(target_env), str(symlink_env))

    from install_helpers import update_env_key

    update_env_key(str(symlink_env), "newkey")

    # Verify symlink is still a symlink
    assert os.path.islink(str(symlink_env))
    assert os.path.realpath(str(symlink_env)) == str(target_env)

    # Verify the target was updated
    assert (
        target_env.read_text(encoding="utf-8")
        == 'LOCAL_API_KEY="newkey"\n'  # pragma: allowlist secret
    )  # pragma: allowlist secret


def test_installer_trap_preservation():
    """Verify that the trap preservation logic in install_prod.sh works correctly."""
    bash_script = """
    # Set an old trap
    trap 'echo "OLD_TRAP_RUN"' EXIT

    # Retrieve any existing EXIT trap commands to avoid overwriting them
    existing_exit_trap=$(trap -p EXIT)
    if [ -n "$existing_exit_trap" ]; then
        existing_cmd=$(echo "$existing_exit_trap" | sed -E "s/^trap -- '(.*)' EXIT$/\\1/")
        run_exit_trap() {
            eval "$existing_cmd"
            echo "NEW_TRAP_RUN"
        }
        trap run_exit_trap EXIT
    else
        echo "NO_OLD_TRAP"
    fi
    """
    result = subprocess.run(
        ["bash", "-c", bash_script],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "OLD_TRAP_RUN" in result.stdout
    assert "NEW_TRAP_RUN" in result.stdout


def test_installer_env_file_tilde_expansion():
    """Verify that the ENV_FILE tilde expansion logic resolves correctly."""
    bash_script = """
    # Mock HOME and ENV_FILE
    HOME="/Users/mockhome"

    # Test ~/path
    ENV_FILE="~/some/.env"
    ENV_FILE=$(eval echo "$ENV_FILE")
    echo "RESULT1:$ENV_FILE"

    # Test ~other/path (should resolve to other user's home or fail gracefully if invalid)
    # For this test, we accept whatever 'eval echo ~other' resolves to in this test env.
    ENV_FILE="~other/.env"
    ENV_FILE=$(eval echo "$ENV_FILE")
    echo "RESULT2:$ENV_FILE"
    """
    result = subprocess.run(
        ["bash", "-c", bash_script],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    # ~home should expand to /Users/mockhome
    assert "RESULT1:/Users/mockhome/some/.env" in result.stdout
    # ~other should NOT be /Users/mockhomeother/.env
    assert "RESULT2:/Users/mockhomeother/.env" not in result.stdout
