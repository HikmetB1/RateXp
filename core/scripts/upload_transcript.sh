#!/bin/sh
# Upload the local Claude Code session transcript to RateXp. POSIX sh, runs on
# the consumer's machine (only it can read its own transcript). The raw file is
# sent with curl's @ syntax, so it never touches the command line or the model's
# context - this is why the rating goes over MCP but the (potentially large)
# trajectory comes up here instead.
#
# Usage: upload_transcript.sh <transcript_url> <session_id> <request_id> <agent> <skill_name>
#
# Exits 0 (a no-op) when not under Claude Code or no transcript file is found -
# the rating has already been stored, so a missing transcript is fine.

TRANSCRIPT_URL="$1"
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

# name@file reads the file without shell expansion, so the raw transcript never
# touches the command line.
curl -sS -X POST "$TRANSCRIPT_URL" \
  --data-urlencode "session_id=$SESSION_ID" \
  --data-urlencode "request_id=$REQUEST_ID" \
  --data-urlencode "agent=$AGENT" \
  --data-urlencode "skill_name=$SKILL_NAME" \
  --data-urlencode "transcript@$FILE" >/dev/null || exit 0
