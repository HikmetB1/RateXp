#!/bin/sh
# Probe the local environment for the harness running this skill and the model
# powering it. Output: "<harness> <model>", "<harness>", or "unknown".
# POSIX-shell only — runs on whatever sh the skill consumer has.

H=""
M=""

if [ -n "$CLAUDECODE" ]; then
  H="claude-code"
  # Claude Code records the model id per assistant turn in the session jsonl.
  if [ -n "$CLAUDE_CODE_SESSION_ID" ]; then
    for f in "$HOME/.claude/projects/"*/"$CLAUDE_CODE_SESSION_ID.jsonl"; do
      [ -f "$f" ] || continue
      M=$(grep -h -o '"model":"[^"]*"' "$f" 2>/dev/null | tail -1 | cut -d'"' -f4)
      [ -n "$M" ] && break
    done
  fi
elif [ -n "$CURSOR_TRACE_ID" ] || [ "$TERM_PROGRAM" = "cursor" ]; then
  H="cursor"
elif [ -n "$WINDSURF_SESSION_ID" ] || [ "$TERM_PROGRAM" = "WindSurf" ]; then
  H="windsurf"
elif [ -n "$CODEX_CLI_VERSION" ] || [ -n "$CODEX_SESSION_ID" ]; then
  H="codex"
elif [ -n "$AIDER_VERSION" ]; then
  H="aider"
fi

printf '%s' "${H:-unknown}${M:+ $M}"

