#!/bin/sh
# Submit RateXp feedback and, on consent, the session transcript in one call.
# POSIX sh, runs on the consumer's machine. Both POSTs here = one approval prompt.
#
# Usage: submit.sh <feedback_url> <transcript_url> <session_id> <request_id> \
#                  <agent> <skill_name> <score> <comment> <consent>
#
#   <score>   : 1, 2, or the word null
#   <comment> : comment text, or the word null
#   <consent> : "yes" to also upload the transcript; anything else skips it
#
# Exits 0 (rating still sent) when not under Claude Code or no transcript is found.

FEEDBACK_URL="$1"
TRANSCRIPT_URL="$2"
SESSION_ID="$3"
REQUEST_ID="$4"
AGENT="$5"
SKILL_NAME="$6"
SCORE="$7"
COMMENT="$8"
CONSENT="$9"

# 1) Feedback - always sent (the server treats "null" as missing).
curl -sS -X POST "$FEEDBACK_URL" \
  --data-urlencode "session_id=$SESSION_ID" \
  --data-urlencode "skill_name=$SKILL_NAME" \
  --data-urlencode "agent=$AGENT" \
  --data-urlencode "request_id=$REQUEST_ID" \
  --data-urlencode "score=$SCORE" \
  --data-urlencode "comment=$COMMENT" >/dev/null || exit 0

# 2) Transcript - only with consent, and only under Claude Code with a session file.
[ "$CONSENT" = "yes" ] || exit 0
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
