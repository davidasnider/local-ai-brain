Fix the following issues in this repo. ONLY fix exactly what is described — do NOT change formatting, refactor, or add any unrelated improvements.

## 1. tests/test_installer.py — SyntaxWarning suppression + raw strings + unused fixture + docstring

In `test_write_env_key_escaping`:

a) Remove lines 95-97 entirely (the `import warnings` and `warnings.filterwarnings("ignore", category=SyntaxWarning)` lines).

b) Remove the unused `tmp_path` parameter from the function signature — change `def test_write_env_key_escaping(tmp_path):` to `def test_write_env_key_escaping():`.

c) Move the docstring `"""Verify that _write_env_key correctly escapes backslashes and double quotes...` to be immediately after the function signature, before any other code. Currently it is after the import and warnings suppression lines so Python does NOT treat it as a real docstring.

d) On line 111, change `"key\\with\\backslashes"` to `r"key\\with\\backslashes"`. Use a Python raw string so `\w` is a literal backslash followed by 'w', not an invalid escape sequence.

e) On line 113, change `'key\\with"both'` to `r"key\\with\"both"`. Use a raw string to avoid invalid escape sequence `\w`.

## 2. scripts/install_helpers.py — IndexError guard in CLI dispatcher

a) In `_cli_dispatch()` function, validate `len(sys.argv)` before accessing `sys.argv[1]`. If fewer than 2 args, print a usage message to stderr and exit with code 1.

b) In `_cli_update_env_key()` function, validate `len(sys.argv)` before accessing `sys.argv[2]`. If fewer than 3 args, print a usage message to stderr and exit with code 1.

c) In `_cli_read_env_key()` function, validate `len(sys.argv)` before accessing `sys.argv[2]`. If fewer than 3 args, print a usage message to stderr and exit with code 1.

## 3. tests/test_installer.py — Add tests for CLI dispatch

Add a new test function `test_cli_dispatch()` that:

- Tests `_cli_dispatch` with valid command `update_env_key` by mocking `sys.argv` to `["prog", "update_env_key", "dummy.env"]`, patching `os.environ["LOCAL_API_KEY_VALUE"]`, and mocking `builtins.open` — verify it calls `update_env_key`.

- Tests `_cli_dispatch` with valid command `read_env_key` by mocking `sys.argv` to `["prog", "read_env_key", "dummy.env"]` and mocking `builtins.open` — verify it reads the key.

- Tests `_cli_dispatch` with an unknown command — verify it prints error to stderr and exits with code 1 (use `pytest.raises(SystemExit)` context manager).

- Tests `_cli_dispatch` with too few arguments (e.g. `sys.argv = ["prog"]`) — verify it prints a usage message and exits with code 1.

Import `_cli_dispatch` from `install_helpers` in the test file. Change the import line to: `from install_helpers import read_env_key, update_env_key, _cli_dispatch`.

## 4. tests/test_installer.py — Add tests for _upsert_api_key (shell function)

Add a new test function `test_shell_upsert_api_key()` that:

- Uses `subprocess.run` to source `install_prod.sh` and call `_upsert_api_key` on a temp file, similar to how `test_write_env_key_escaping` already tests `_write_env_key` via subprocess.

- Tests these cases:
  a) File without LOCAL_API_KEY gets the key appended.
  b) File with LOCAL_API_KEY gets the key updated with a new value.
  c) Empty file gets the key appended correctly.
  d) Missing file: the function should create the file with the key.

After making ALL changes, run `python3 -m pytest tests/test_installer.py -v` to verify all tests pass.
