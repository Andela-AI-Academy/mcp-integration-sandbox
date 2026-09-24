#!/usr/bin/env bash
# PreToolUse hook: refuse shell commands that reach for ops.db directly.
#
# Why this exists
# ---------------
# The ops-db MCP connection is read-only, but that only governs the MCP path.
# The agent also has a shell, and ops.db is just a file — a python or sqlite3
# one-liner can write to it without ever touching the server. This hook closes
# that gap by reading the whole command string (so wrapped forms like
# `bash -c "..."` are caught too) and refusing anything that names the database.
#
# Exit 2 blocks the tool call and returns this message to Claude.

input=$(cat)

cmd=$(printf '%s' "$input" | python3 -c \
  'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))' 2>/dev/null)

# `make seed` is the sanctioned way to rebuild, and does not name the file.
case "$cmd" in
  *ops.db*)
    echo "Blocked by project hook: reach the operational database through the \
ops-db MCP connection (read-only), not by opening the file directly. \
To rebuild it, run 'make seed'." >&2
    exit 2
    ;;
esac

exit 0
