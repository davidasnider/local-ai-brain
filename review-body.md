## Review findings

After thorough manual review of all changed files in this PR (34 commits, extensively iterated via prior agy rounds), the code quality is high overall. I found **one remaining issue**:

---

### 1. Low — `printf -v` requires bash 4.1+, fails on macOS default bash 3.2

**File:** `.agents/skills/start-backends/SKILL.md`, line 221

```bash
printf -v "$_var" ''
```

`printf -v` (assign output to variable by name) was introduced in **bash 4.1** (2009). macOS ships **bash 3.2** by default. Users running this on a stock macOS system will get:

```
printf: -v: invalid option
```

**Impact:** The variable $_var (LLM_PID/STT_PID/TTS_PID) won't be cleared after a clean process exit. The monitoring loop's "all done" detection will then check stale PIDs via `kill -0`, which may orphan the "continue with remaining services" path. Edge case — only triggers on processes that exit cleanly (code 0) while others keep running.

**Recommendation:** Replace with `unset "$_var"` — works on bash 3.2+:

```bash
unset "$_var"
```

This is semantically different (unset vs empty string) but achieves the same effect in the downstream checks since both `[ -z "" ]` and `[ -z "${_var:+x}" ]` evaluate to true for an unset name.

---

### Additional observations (no change needed)

- Shell injection vectors from .env are properly mitigated via regex key validation + `shlex.quote()`.
- YAML parsing in `update-deps` uses `yaml.safe_load` with `isinstance` guard — correct.
- `GIT_TERMINAL_PROMPT=0` prevents interactive credential prompts on network failures — good practice.
- `/dev/tcp` portability issue was already resolved by replacing with Python socket checks (good call).
- HF model URL resolution logic in `check_model()` correctly handles all edge cases (local paths, HTTP/HTTPS, file extensions, ambiguous org/repo patterns).
- Port pre-check in `start-backends` prevents port conflicts before launching services.
- Trap handler correctly removes traps on first call to avoid double-cleanup.

**Verdict:** Code is clean and well-defended. Only the `printf -v` portability issue qualifies as actionable — everything else is solid.
