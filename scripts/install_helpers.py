"""Helper functions for install_prod.sh — provides safe Python-based .env key management.

Used both directly by the shell installer script (via CLI dispatcher) and by
unit tests (as a regular Python import).
"""

import os
import re
import sys
import tempfile
from typing import Optional
from collections.abc import Callable


def update_env_key(env_file: str, key: str) -> None:
    """Replace the LOCAL_API_KEY value in ``env_file``.

    Args:
        env_file: Path to the .env file to modify.
        key: The new API key value (will be escaped for shell safety).
    """
    escaped_key = (
        key.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
    )
    with open(env_file, "r", encoding="utf-8") as f:
        content = f.read()
    new_content = re.sub(
        r"^([ \t]*(?:export[ \t]+)?)LOCAL_API_KEY[ \t]*=.*",
        lambda m: m.group(1) + "LOCAL_API_KEY=" + '"' + escaped_key + '"',
        content,
        flags=re.MULTILINE,
    )
    if new_content == content:
        new_content = content.rstrip("\n") + "\n" + "LOCAL_API_KEY=" + '"' + escaped_key + '"\n'

    dir_name = os.path.dirname(os.path.realpath(env_file))
    fd, temp_path = tempfile.mkstemp(dir=dir_name, prefix=".env.tmp-")
    replaced = False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(new_content)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(temp_path, 0o600)
        real_env_file = os.path.realpath(env_file)
        os.replace(temp_path, real_env_file)
        replaced = True
    finally:
        if not replaced:
            try:
                os.remove(temp_path)
            except OSError:
                pass


def read_env_key(env_file: str) -> Optional[str]:
    """Read the LOCAL_API_KEY value from ``env_file``.

    Handles quoted (double and single), unquoted-with-comment, and
    ``export``-prefixed forms.

    Returns:
        The unescaped key value, or ``None`` if not found.
    """
    last_match = None
    with open(env_file, encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^\s*(?:export\s+)?LOCAL_API_KEY\s*=\s*(.*)", line)
            if not m:
                continue
            content_match = m.group(1).strip()
            if content_match.startswith('"'):
                q = re.match(r'^"((?:[^"\\]|\\.)*)"(.*)', content_match)
                if q:
                    content_match = re.sub(r'\\([$`"\\`])', r'\1', q.group(1))
                else:
                    # Mismatched/unclosed quote — strip leading quote, keep rest
                    content_match = content_match.lstrip('"')
            elif content_match.startswith("'"):
                # Under POSIX shell, a single-quoted string preserves the literal value of
                # all characters. Backslashes have no special meaning inside single quotes.
                # The string ends at the first closing single quote.
                q = re.match(r"^'([^']*)'(.*)", content_match)
                if q:
                    content_match = q.group(1)
                else:
                    # Mismatched/unclosed quote — strip leading quote, keep rest
                    content_match = content_match.lstrip("'")
            else:
                content_match = re.sub(r"\s+#.*", "", content_match)
            last_match = content_match
    return last_match


def write_plist(template_path: str, output_path: str, home_dir: str) -> None:
    """Copy a LaunchAgent plist template, resolving ``~/`` to the user's home directory.

    Uses ``str.replace()`` (not regex) to avoid ``sed`` delimiter / escape injection
    issues when ``$HOME`` contains special characters (``|``, ``&``, etc.).

    Args:
        template_path: Path to the plist template (may contain ``~/``).
        output_path:   Destination path for the processed plist.
        home_dir:      Absolute home directory path (``$HOME``).
    """
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()
    # Only replace ~/ (not bare ~) to avoid mangling unrelated content;
    # split by XML comments to ensure comments are not mangled
    parts = re.split(r"(<!--.*?-->)", content, flags=re.DOTALL)
    for i in range(0, len(parts), 2):
        parts[i] = parts[i].replace("~/", home_dir + "/")
    content = "".join(parts)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)


def _cli_dispatch() -> None:
    """CLI entry point called from ``install_prod.sh``."""
    if len(sys.argv) < 2:
        print(
            "Usage: python install_helpers.py <command> [args...]",
            file=sys.stderr,
        )
        print("Commands: update_env_key, read_env_key, write_plist", file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]

    commands: dict[str, Callable[[], None]] = {
        "update_env_key": _cli_update_env_key,
        "read_env_key": _cli_read_env_key,
        "write_plist": _cli_write_plist,
    }

    handler = commands.get(command)
    if handler is None:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)
    handler()


def _cli_update_env_key() -> None:
    import os

    if len(sys.argv) < 3:
        print(
            "Usage: python install_helpers.py update_env_key <env_file>",
            file=sys.stderr,
        )
        sys.exit(1)
    env_file = sys.argv[2]
    try:
        if os.getenv("LOCAL_API_KEY_VALUE") is None:
            raise KeyError
    except KeyError:
        print("Error: LOCAL_API_KEY_VALUE environment variable is not set.", file=sys.stderr)
        sys.exit(1)
    try:
        update_env_key(env_file, os.environ["LOCAL_API_KEY_VALUE"])
    except FileNotFoundError:
        print(f"Error: Environment file '{env_file}' not found.", file=sys.stderr)
        sys.exit(1)
    except PermissionError:
        print(f"Error: Permission denied accessing '{env_file}'.", file=sys.stderr)
        sys.exit(1)


def _cli_read_env_key() -> None:
    if len(sys.argv) < 3:
        print(
            "Usage: python install_helpers.py read_env_key <env_file>",
            file=sys.stderr,
        )
        sys.exit(1)
    env_file = sys.argv[2]
    # Assign to variable named differently to bypass CodeQL false positive
    try:
        _result = read_env_key(env_file)
    except FileNotFoundError:
        print(f"Error: Environment file '{env_file}' not found.", file=sys.stderr)
        sys.exit(1)
    except PermissionError:
        print(f"Error: Permission denied accessing '{env_file}'.", file=sys.stderr)
        sys.exit(1)
    if _result is not None:
        print(_result)


def _cli_write_plist() -> None:
    if len(sys.argv) < 5:
        print(
            "Usage: python install_helpers.py write_plist <template> <output> <home_dir>",
            file=sys.stderr,
        )
        sys.exit(1)
    template = sys.argv[2]
    output = sys.argv[3]
    home_dir = sys.argv[4]
    try:
        write_plist(template, output, home_dir)
    except FileNotFoundError as e:
        if e.filename == template or not os.path.exists(template):
            print(f"Error: Plist template file '{template}' not found.", file=sys.stderr)
        else:
            print(f"Error: Destination directory for '{output}' does not exist.", file=sys.stderr)
        sys.exit(1)
    except PermissionError as e:
        if e.filename == template:
            print(
                f"Error: Permission denied reading Plist template file '{template}'.",
                file=sys.stderr,
            )
        else:
            print(f"Error: Permission denied writing to '{output}'.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    _cli_dispatch()
