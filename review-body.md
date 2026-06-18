## Review findings

All findings from the manual review have been resolved:

- **`printf -v` Portability:** The `printf -v` option was replaced in commit 67587ba (resolved). The fix used `eval "$_var="` rather than `unset` because the script uses `set -euo pipefail`; `unset` would break `nounset` mode.
- **Exit Code 127 Handling:** The exit code 127 handling was improved to be transparent about uncertainty when a process is reaped before wait is called.
- **YAML Models Iteration:** An `isinstance` guard was added for the YAML models iteration to avoid type errors.

---

### Additional observations

- Shell injection vectors from .env are properly mitigated via regex key validation + `shlex.quote()`.
- YAML parsing in `update-deps` uses `yaml.safe_load` with `isinstance` guard — correct.
- `GIT_TERMINAL_PROMPT=0` prevents interactive credential prompts on network failures — good practice.
- `/dev/tcp` portability issue was already resolved by replacing with Python socket checks (good call).
- HF model URL resolution logic in `check_model()` correctly handles all edge cases (local paths, HTTP/HTTPS, file extensions, ambiguous org/repo patterns).
- Port pre-check in `start-backends` prevents port conflicts before launching services.
- Trap handler correctly removes traps on first call to avoid double-cleanup.

**Verdict:** Code is clean, well-defended, and all issues are fully resolved.
