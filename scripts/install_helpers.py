"""Helper functions for install_prod.sh — provides safe Python-based .env key management.

Used both directly by the shell installer script (via CLI dispatcher) and by
unit tests (as a regular Python import).
"""

import os
import re
import sys
from collections.abc import Callable


def update_env_key(env_file: str, key: str) -> None:
    """Replace the LOCAL_API_KEY value in ``env_file``.

    Args:
        env_file: Path to the .env file to modify.
        key: The new API key value (will be escaped for shell safety).
    """
    escaped_key = key.replace("\\", "\\\\").replace('"', '\\"')
    try:
        with open(env_file, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        raise FileNotFoundError(f"Environment file not found: '{env_file}'")
    new_content = re.sub(
        r"^([ \t]*(?:export[ \t]+)?)LOCAL_API_KEY[ \t]*=.*",
        lambda m: m.group(1) + 'LOCAL_API_KEY="' + escaped_key + '"',
        content,
        flags=re.MULTILINE,
    )
    with open(env_file, "w", encoding="utf-8") as f:
        f.write(new_content)


def read_env_key(env_file: str) -> str | None:
    """Read the LOCAL_API_KEY value from ``env_file``.

    Handles quoted (double and single), unquoted-with-comment, and
    ``export``-prefixed forms.

    Returns:
        The unescaped key value, or ``None`` if not found.
    """
    try:
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                m = re.match(r"^\s*(?:export\s+)?LOCAL_API_KEY\s*=\s*(.*)", line)
                if not m:
                    continue
                val = m.group(1).strip()
                if val.startswith('"'):
                    q = re.match(r"^\"((?:[^\"\\]|\\.)*)\"(.*)", val)
                    if q:
                        val = q.group(1).replace('\\"', '"').replace("\\\\", "\\")
                    else:
                        return None
                elif val.startswith("'"):
                    q = re.match(r"^\'((?:[^\'\\]|\\.)*)\'(.*)", val)
                    if q:
                        val = q.group(1).replace("\\'", "'").replace("\\\\", "\\")
                    else:
                        return None
                else:
                    val = re.sub(r"\s+#.*", "", val)
                return val
    except FileNotFoundError:
        raise FileNotFoundError(f"Environment file not found: '{env_file}'")
    return None


def write_plist(template_file: str, target_file: str, home_dir: str) -> None:
    """Read plist template, replace '~/' with home_dir path, and write to target_file."""
    if not os.path.exists(template_file):
        raise FileNotFoundError(f"Template file not found: '{template_file}'")
    with open(template_file, "r", encoding="utf-8") as f:
        content = f.read()
    # Normalize home_dir to ensure it ends with '/' when substituting '~/'
    replacement = home_dir.rstrip("/") + "/"
    new_content = content.replace("~/", replacement)
    with open(target_file, "w", encoding="utf-8") as f:
        f.write(new_content)


def _cli_dispatch() -> None:
    """CLI entry point called from ``install_prod.sh``."""
    if len(sys.argv) < 2:
        print("Usage: install_helpers.py <command> [args]", file=sys.stderr)
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
    if len(sys.argv) < 3:
        print("Usage: install_helpers.py update_env_key <env_file>", file=sys.stderr)
        sys.exit(1)
    env_file = sys.argv[2]
    key = os.environ.get("LOCAL_API_KEY_VALUE")
    if key is None:
        print("Error: LOCAL_API_KEY_VALUE environment variable is not set.", file=sys.stderr)
        sys.exit(1)
    try:
        update_env_key(env_file, key)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _cli_read_env_key() -> None:
    if len(sys.argv) < 3:
        print("Usage: install_helpers.py read_env_key <env_file>", file=sys.stderr)
        sys.exit(1)
    env_file = sys.argv[2]
    try:
        val = read_env_key(env_file)
        if val is not None:
            print(val)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _cli_write_plist() -> None:
    if len(sys.argv) < 5:
        print(
            "Usage: install_helpers.py write_plist <template_file> <target_file> <home_dir>",
            file=sys.stderr,
        )
        sys.exit(1)
    template_file = sys.argv[2]
    target_file = sys.argv[3]
    home_dir = sys.argv[4]
    try:
        write_plist(template_file, target_file, home_dir)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    _cli_dispatch()
