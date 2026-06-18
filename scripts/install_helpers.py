import re
import sys


def update_env_key(env_file_path: str, new_key_value: str) -> None:
    """Read the env file, use re.sub with MULTILINE to replace LOCAL_API_KEY=.* line.

    The function takes the key value directly (not from environment variable).
    Escape backslashes and double quotes in the key value before writing.
    Write the modified content back to the file.
    """
    # Escape backslashes first, then double quotes
    escaped_key = new_key_value.replace("\\", "\\\\").replace('"', '\\"')

    with open(env_file_path, "r", encoding="utf-8") as f:
        content = f.read()

    new_content = re.sub(
        r"^([ \t]*(?:export[ \t]+)?)LOCAL_API_KEY[ \t]*=.*",
        lambda m: m.group(1) + 'LOCAL_API_KEY="' + escaped_key + '"',
        content,
        flags=re.MULTILINE,
    )

    with open(env_file_path, "w", encoding="utf-8") as f:
        f.write(new_content)


def read_env_key(env_file_path: str) -> str | None:
    """Read the env file, parse LOCAL_API_KEY value supporting double-quoted,

    single-quoted, and unquoted values.
    Strip inline comments (#) from unquoted values.
    Return the parsed value or None if not found.
    """
    try:
        with open(env_file_path, "r", encoding="utf-8") as f:
            for line in f:
                m = re.match(r"^\s*(?:export\s+)?LOCAL_API_KEY\s*=\s*(.*)", line)
                if m:
                    val = m.group(1).strip()
                    if val.startswith('"'):
                        q = re.match(r'^"((?:[^"\\]|\\.)*)"(.*)', val)
                        if q:
                            val = q.group(1).replace('\\"', '"').replace("\\\\", "\\")
                    elif val.startswith("'"):
                        q = re.match(r"^'((?:[^'\\]|\\.)*)'(.*)", val)
                        if q:
                            val = q.group(1).replace("\\'", "'").replace("\\\\", "\\")
                    else:
                        val = re.sub(r"\s+#.*", "", val)
                    return val
    except FileNotFoundError:
        pass
    return None


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: install_helpers.py <action> [args...]", file=sys.stderr)
        sys.exit(1)

    action = sys.argv[1]
    if action == "update_env_key":
        if len(sys.argv) < 4:
            print(
                "Usage: install_helpers.py update_env_key <env_file_path> <new_key_value>",
                file=sys.stderr,
            )
            sys.exit(1)
        update_env_key(sys.argv[2], sys.argv[3])
    elif action == "read_env_key":
        if len(sys.argv) < 3:
            print(
                "Usage: install_helpers.py read_env_key <env_file_path>",
                file=sys.stderr,
            )
            sys.exit(1)
        val = read_env_key(sys.argv[2])
        if val is not None:
            print(val)
    else:
        print(f"Unknown action: {action}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
