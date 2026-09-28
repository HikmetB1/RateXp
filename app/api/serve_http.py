"""Read-only dashboard API over the stored feedback and transcripts, plus the built UI.

This service never writes - core is the only writer - so it can run with a read-only
database identity. The one read source is opened at startup and every endpoint goes
through it, so nothing here knows which of the four sources is actually answering.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from contextlib import asynccontextmanager
from pathlib import Path

from api.broadcast_live import broadcast_changes, hub
from api.build_snapshot import build_snapshot, display_name, row_to_feedback, row_to_transcript
from api.record_schemas import Feedback, QueryRequest, Transcript
from api.trim_result_rows import apply_download_rule, jsonable, most_recent
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from load_config import (
    CORE_URL,
    LIST_MAX_LIMIT,
    LIST_VIEW_LIMIT,
    QUERY_ENABLED,
    QUERY_MAX_ROWS,
    QUERY_TIMEOUT_MS,
    TOP_SKILLS_LIMIT,
    WS_ENABLED,
)
from modules.read.open_read_source import open_read_source

ENV = os.environ.get("RATEXP_ENV", "local").lower()
CORS_ORIGINS_RAW = os.environ.get("RATEXP_CORS_ORIGINS")
# app/static, one level up from this package - the UI the Dockerfile builds in. Resolved
# from __file__ so the working directory doesn't matter. Absent in a checkout.
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def _resolve_cors_origins() -> list[str]:
    # Truthy (not `is not None`) so a "" injected by compose behaves like absent.
    if CORS_ORIGINS_RAW:
        return [o.strip() for o in CORS_ORIGINS_RAW.split(",") if o.strip()]
    if ENV in ("", "local"):
        return ["*"]
    raise RuntimeError(
        f"RATEXP_ENV={ENV!r} requires RATEXP_CORS_ORIGINS to be set "
        "(comma-separated list of allowed origins)."
    )


# Shared by the CORS middleware and the WebSocket origin check (CORS doesn't cover WS handshakes).
ALLOWED_ORIGINS = _resolve_cors_origins()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.read = open_read_source()
    # One broadcaster fans snapshots to all clients, so read load tracks writes, not viewers.
    broadcaster = asyncio.create_task(broadcast_changes(app.state.read)) if WS_ENABLED else None
    try:
        yield
    finally:
        if broadcaster is not None:
            broadcaster.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await broadcaster
        app.state.read.close()


# Hide Swagger/ReDoc/OpenAPI outside local dev.
_docs_kwargs = (
    {} if ENV in ("", "local") else {"docs_url": None, "redoc_url": None, "openapi_url": None}
)

app = FastAPI(title="ratexp-app", version="1.0.0", lifespan=lifespan, **_docs_kwargs)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/meta")
def meta() -> dict:
    """What the UI needs to render the filter box for the active read source -
    whether the /query box is on, and the source's query language + an example -
    and the core its install popup tells users to install from."""
    read = app.state.read
    return {
        "core_url": CORE_URL,
        "query_enabled": QUERY_ENABLED,
        "read_source": read.name,
        "query_language": read.query_language,
        "query_example": read.query_example,
    }


@app.get("/feedback")
def list_feedback(
    limit: int = Query(LIST_VIEW_LIMIT, ge=1, le=LIST_MAX_LIMIT),
    full: bool = False,
) -> list[Feedback]:
    # full=true (the dashboard's Download) returns up to the hard ceiling; else the small view.
    try:
        rows = app.state.read.select_feedback(LIST_MAX_LIMIT if full else limit)
    except Exception as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"db error: {e!r}") from e
    return [row_to_feedback(r) for r in rows]


@app.get("/transcript")
def list_transcript(
    limit: int = Query(LIST_VIEW_LIMIT, ge=1, le=LIST_MAX_LIMIT),
    full: bool = False,
) -> list[Transcript]:
    # full=true (the dashboard's Download) returns every transcript up to the hard ceiling.
    try:
        rows = app.state.read.select_transcript(LIST_MAX_LIMIT if full else limit)
    except Exception as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"db error: {e!r}") from e
    return [row_to_transcript(r) for r in rows]


@app.get("/stats/top-skills")
def top_skills(limit: int = Query(TOP_SKILLS_LIMIT, ge=1, le=LIST_MAX_LIMIT)) -> dict:
    """Most-rated skills with their good/bad tally, for the "Top skills" panel."""
    try:
        skills = app.state.read.select_top_skills(limit)
    except Exception as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"db error: {e!r}") from e
    return {"skills": skills}


@app.get("/snapshot")
def snapshot() -> dict:
    """The dashboard's whole initial view in one call: feedback + their transcripts + stats.

    Same shape as the live WebSocket snapshot, so the first paint and later updates agree.
    """
    try:
        return build_snapshot(app.state.read)
    except Exception as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"db error: {e!r}") from e


@app.post("/query")
def run_query(req: QueryRequest) -> dict:
    """Run a guarded, read-only query for the dashboard's filter/CSV box.

    The query is in the read source's own language (SQL for PostgreSQL, DQL for
    Dynatrace); the read adapter validates it, caps rows, and runs it read-only.
    """
    if not QUERY_ENABLED:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "query endpoint disabled")

    read = app.state.read
    # The adapter validates + caps + runs the query in its language; newest-first trimming
    # (and the Download single-skill rule) happen below.
    try:
        columns, rows = read.run_query(req.query, QUERY_MAX_ROWS, QUERY_TIMEOUT_MS)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"query error: {e}") from e
    except Exception as e:
        # Most other failures here are the user's query, so surface as 400, not 503.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"query error: {e!r}") from e

    result = [dict(zip(columns, (jsonable(v) for v in row), strict=False)) for row in rows]
    # Give filtered rows the same Name as the live table, unless the query picked its own.
    for r in result:
        if "skill_name" in r or "session_id" in r:
            r.setdefault("name", display_name(r.get("skill_name"), r.get("session_id")))
    fetched_truncated = len(rows) >= QUERY_MAX_ROWS
    if req.full:
        # Download: single skill -> all of it (newest first); else the most-recent view.
        result, truncated = apply_download_rule(result, fetched_truncated)
    else:
        # Filter view: newest first, capped to the view (or an explicit, smaller limit).
        view_cap = LIST_VIEW_LIMIT if req.limit is None else max(1, min(req.limit, QUERY_MAX_ROWS))
        result, truncated = most_recent(result, view_cap, fetched_truncated)

    # Carry the shown rows' own trajectories so the filtered table resolves them itself,
    # rather than borrowing the live preview's index (which only holds the newest rows).
    # Skipped for Download (full=true): that path fetches every transcript separately.
    transcripts: list[dict] = []
    if not req.full:
        request_ids = [r["request_id"] for r in result if r.get("request_id")]
        session_ids = [r["session_id"] for r in result if r.get("session_id")]
        transcripts = [
            row_to_transcript(t).model_dump()
            for t in read.select_transcripts_by_ids(request_ids, session_ids)
        ]

    return {
        "columns": columns,
        "rows": result,
        "transcripts": transcripts,
        "row_count": len(result),
        "truncated": truncated,
    }


def _ws_origin_allowed(websocket: WebSocket) -> bool:
    # CORS middleware doesn't guard WS handshakes, so enforce the allowlist here.
    if "*" in ALLOWED_ORIGINS:
        return True
    origin = websocket.headers.get("origin")
    return bool(origin) and origin in ALLOWED_ORIGINS


@app.websocket("/ws")
async def ws_feed(websocket: WebSocket) -> None:
    """Live feed: a snapshot on connect, then on every change. Server -> dashboard only."""
    if not WS_ENABLED:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    if not _ws_origin_allowed(websocket):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await websocket.accept()
    await hub.add(websocket)
    try:
        # Paint immediately so a fresh tab doesn't wait for the next interval.
        await websocket.send_json(await asyncio.to_thread(build_snapshot, app.state.read))
        while True:
            await websocket.receive_text()  # keepalive; content ignored
    except WebSocketDisconnect:
        pass
    finally:
        await hub.remove(websocket)


# Serve the built UI from the API origin; mounted last so API routes win.
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="dashboard")
