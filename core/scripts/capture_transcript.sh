#!/bin/sh
# Upload the current Claude Code session transcript to RateXp, once the user has
# consented. Runs on the consumer's machine (only the client can see its own
# session files). POSIX-shell only.
#
# Usage: capture_transcript.sh <submit_url> <session_id> <request_id> <agent> <skill_name>
#
# Quietly does nothing (exit 0) when not running under Claude Code or when no
# transcript file is found — feedback submission must never be blocked by this.

SUBMIT_URL="$1"
SESSION_ID="$2"
REQUEST_ID="$3"
AGENT="$4"
SKILL_NAME="$5"

[ -n "$CLAUDECODE" ] || exit 0
[ -n "$CLAUDE_CODE_SESSION_ID" ] || exit 0

FILE=""
for f in "$HOME/.claude/projects/"*/"$CLAUDE_CODE_SESSION_ID.jsonl"; do
  [ -f "$f" ] || continue
  FILE="$f"
  break
done
[ -n "$FILE" ] || exit 0

# --data-urlencode "name@file" reads the file contents without any shell
# expansion, so the raw transcript never touches the command line.
curl -sS -X POST "$SUBMIT_URL" \
  --data-urlencode "session_id=$SESSION_ID" \
  --data-urlencode "request_id=$REQUEST_ID" \
  --data-urlencode "agent=$AGENT" \
  --data-urlencode "skill_name=$SKILL_NAME" \
  --data-urlencode "transcript@$FILE" >/dev/null || exit 0
