"""The RateXp MCP server - the only ingestion surface.

A skill pairs a `.mcp.json` client with this server (streamable HTTP, mounted at
`/mcp` by server.py). Three tools replace the old snippet/feedback/transcript
flow:

  - `feedback`          - hands back the survey steps (with sampling), like the
                          old GET /snippet.
  - `submit_feedback`   - stores the rating, like the old POST /feedback.
  - `submit_trajectory` - stores the consented conversation, like POST /transcript.

The heavy lifting (ATIF conversion, size-limit, PII redaction, DB write) is
reused from atif.py / ingest.py unchanged.
"""

from __future__ import annotations

import os
import random
import uuid
from pathlib import Path

from atif import claude_jsonl_to_atif
from config import DEFAULT_SURVEY_EVERY
from ingest import ingest_feedback, ingest_transcript
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from models import Feedback, Transcript

PROMPT_FILE = Path(__file__).resolve().parent / "prompt" / "prompt.md"
SKIP_FILE = Path(__file__).resolve().parent / "prompt" / "skip.md"

# Public base URL of this core, so the feedback prompt can hand the agent absolute
# URLs for the transcript helper + endpoint (the trajectory is uploaded straight to
# HTTP, not through MCP). Set RATEXP_PUBLIC_URL in deployment; defaults to local.
PUBLIC_URL = os.environ.get("RATEXP_PUBLIC_URL", "http://localhost:8000").rstrip("/")
TRANSCRIPT_URL = f"{PUBLIC_URL}/transcript"
TRANSCRIPT_SH_URL = f"{PUBLIC_URL}/upload_transcript.sh"

# stateless_http + json_response: every tool call is a self-contained POST, so
# there is no long-lived SSE stream for the body-size / rate-limit middleware in
# server.py to break, and the middleware still guards each request. The internal
# route sits at "/" so that, mounted at "/mcp", the endpoint is exactly /mcp.
#
# DNS-rebinding protection off: FastMCP otherwise auto-enables it (allowing only
# localhost) because our default host is loopback, which 421s every request once
# deployed behind Azure's proxy under the real hostname. This is a public
# ingestion endpoint, so host/origin allow-listing isn't the right control here.
mcp = FastMCP(
    "ratexp",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


@mcp.tool()
def feedback(every: int | None = None) -> str:
    """Start the RateXp feedback flow; returns the survey steps to follow.

    Call this where your skill wants feedback. It surveys roughly 1 in `every`
    runs (omit for the server default; 1 always asks) and returns either the
    survey instructions or a short "skip this run" note. Do exactly what it
    returns: collect the rating, then call submit_feedback - and, only on
    consent, submit_trajectory - passing the session_id and request_id it gives
    you (the request_id is what links a rating to its trajectory).
    """
    if every is None:
        every = DEFAULT_SURVEY_EVERY
    if every < 1:
        every = 1
    # randrange(N) == 0 fires ~1 in N times; every=1 always asks.
    if random.randrange(every) != 0:
        return SKIP_FILE.read_text(encoding="utf-8")
    return (
        PROMPT_FILE.read_text(encoding="utf-8")
        .replace("{{TRANSCRIPT_URL}}", TRANSCRIPT_URL)
        .replace("{{TRANSCRIPT_SH_URL}}", TRANSCRIPT_SH_URL)
        .replace("{{SESSION_ID}}", str(uuid.uuid4()))
        .replace("{{REQUEST_ID}}", str(uuid.uuid4()))
    )


@mcp.tool()
def submit_feedback(
    skill_name: str,
    agent: str,
    session_id: str,
    request_id: str,
    score: int | None = None,
    comment: str | None = None,
) -> str:
    """Store a rating. score: 1 = good, 2 = bad; omit it if neither was chosen.

    `agent` identifies the calling runtime (e.g. "claude-code claude-opus-4-8").
    Pass the session_id and request_id from `feedback` so the rating and its
    trajectory stay linked.
    """
    ingest_feedback(
        Feedback(
            skill_name=skill_name,
            agent=agent,
            session_id=session_id,
            request_id=request_id,
            score=score,
            comment=comment,
        )
    )
    return "stored"


@mcp.tool()
def submit_trajectory(
    skill_name: str,
    agent: str,
    session_id: str,
    request_id: str,
    transcript: str | None = None,
    atif: dict | None = None,
) -> str:
    """Store the consented conversation, linked by request_id to the rating.

    Provide exactly one of:
      - transcript: the raw Claude Code session .jsonl text (converted to ATIF,
        then PII-redacted, server-side); or
      - atif: an already-built ATIF dict.
    Oversized conversations are stored as a meta-only stub (steps dropped).
    """
    if transcript is not None and transcript.strip():
        atif_doc = claude_jsonl_to_atif(transcript, session_id=session_id, agent=agent)
    elif atif is not None:
        atif_doc = atif
    else:
        raise ValueError("provide either transcript (raw .jsonl) or atif (dict)")
    ingest_transcript(
        Transcript(
            skill_name=skill_name,
            agent=agent,
            session_id=session_id,
            request_id=request_id,
            atif=atif_doc,
        )
    )
    return "stored"
