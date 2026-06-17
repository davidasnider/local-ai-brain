---
name: tail-logs
description: Opens a new iTerm2 window to tail the local development server logs in real-time.
---

# tail-logs

This skill opens a new iTerm2 window to tail the local development server logs.

## Instructions

The development server (`run-dev`) outputs its live logs to `/tmp/localbrain-dev.log`.

To launch iTerm2 automatically and begin tailing the logs, execute this command:

```bash
osascript -e 'tell application "iTerm"
    activate
    if not (exists window 1) then
        create window with default profile
    else
        tell current window
            create tab with default profile
        end tell
    end if
    tell current window
        tell current session
            write text "tail -f /tmp/localbrain-dev.log"
        end tell
    end tell
end tell'
```

*Note: If the user explicitly asks to use their integrated terminal instead of iTerm, just provide them the command `tail -f /tmp/localbrain-dev.log` so they can run it manually.*
