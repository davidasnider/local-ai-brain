"""Helper functions for install_prod.sh — provides safe Python-based .env key management.

Used both directly by the shell installer script (via CLI dispatcher) and by
unit tests (as a regular Python import).
"""

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
    with open(env_file, "r", encoding="utf-8") as f:
        content = f.read()
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
            elif val.startswith("'"):
                q = re.match(r"^\'((?:[^\'\\]|\\.)*)\'(.*)", val)
                if q:
                    val = q.group(1).replace("\\'", "'").replace("\\\\", "\\")
            else:
                val = re.sub(r"\s+#.*", "", val)
            return val
    return None


def _cli_dispatch() -> None:
    """CLI entry point called from ``install_prod.sh``."""
    if len(sys.argv) < 2:
        print("Usage: install_helpers.py <command> [args]", file=sys.stderr)
        sys.exit(1)
    command = sys.argv[1]

    commands: dict[str, Callable[[], None]] = {
        "update_env_key": _cli_update_env_key,
        "read_env_key": _cli_read_env_key,
    }

    handler = commands.get(command)
    if handler is None:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)
    handler()


def _cli_update_env_key() -> None:
    import os

    if len(sys.argv) < 3:
        print("Usage: install_helpers.py update_env_key <env_file>", file=sys.stderr)
        sys.exit(1)
    env_file = sys.argv[2]
    if "LOCAL_API_KEY_VALUE" not in os.environ:
        print("Error: LOCAL_API_KEY_VALUE environment variable not set", file=sys.stderr)
        sys.exit(1)
    key = os.environ["LOCAL_API_KEY_VALUE"]
    update_env_key(env_file, key)


def _cli_read_env_key() -> None:
    if len(sys.argv) < 3:
        print("Usage: install_helpers.py read_env_key <env_file>", file=sys.stderr)
        sys.exit(1)
    env_file = sys.argv[2]
    val = read_env_key(env_file)
    if val is not None:
        print(val)


if __name__ == "__main__":
    _cli_dispatch()
