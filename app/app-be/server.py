"""Dashboard service: a read-only API over the feedback/transcript tables,
plus the built dashboard UI served from the same origin.

This service never writes - core is the only writer - so it can run with a
read-only database identity. It exposes list/stats/query endpoints and a live
WebSocket feed, and (in the built image) serves the React dashboard.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from config import (
    LIST_MAX_LIMIT,
    LIST_VIEW_LIMIT,
    QUERY_ENABLED,
    QUERY_MAX_ROWS,
    QUERY_TIMEOUT_MS,
    TOP_SKILLS_LIMIT,
    WS_BROADCAST_INTERVAL_MS,
    WS_ENABLED,
)
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from models import Feedback, QueryRequest, Transcript
from read_adapters import get_read_adapter

ENV = os.environ.get("RATEXP_ENV", "local").lower()
CORS_ORIGINS_RAW = os.environ.get("RATEXP_CORS_ORIGINS")
_STATIC_DIR = Path(__file__).resolve().parent / "static"


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

# Query validation now lives in the read adapter (each source validates its own
# language - SQL in read_adapters/utils/postgres.py, DQL in read_adapters/utils/dynatrace.py).


def _jsonable(value):
    """Match the list endpoints' wire format: datetime -> ISO8601 Z string."""
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds").replace("+00:00", "Z")
    return value


def _most_recent(
    rows: list[dict], limit: int | None, fetched_truncated: bool
) -> tuple[list[dict], bool]:
    """Order newest-first by created_at, optionally trimmed to `limit` rows.

    created_at is an ISO-8601 Z string here, so a plain reverse sort is newest-first;
    rows without it sort last but keep their relative order. `truncated` stays true if the
    fetch hit the hard cap or trimming dropped rows.
    """
    ordered = sorted(rows, key=lambda r: r.get("created_at") or "", reverse=True)
    trimmed = ordered if limit is None else ordered[:limit]
    return trimmed, fetched_truncated or len(trimmed) < len(rows)


def _apply_download_rule(rows: list[dict], fetched_truncated: bool) -> tuple[list[dict], bool]:
    """Decide what a full (Download) query actually returns, judged over the whole result.

    A result that resolves to a single skill is exported in full (newest first); anything
    else - more than one skill, or a shape without a usable skill_name column - is trimmed
    to the most recent view-limit rows. Deciding here (server-side, over the full result)
    keeps the rule authoritative instead of guessed from the small on-screen preview.
    """
    skills = {r.get("skill_name") for r in rows}
    single_skill = (
        bool(rows)
        and "skill_name" in rows[0]
        and skills == {rows[0]["skill_name"]}
        and None not in skills
    )
    return _most_recent(rows, None if single_skill else LIST_VIEW_LIMIT, fetched_truncated)


# Shared by the HTTP endpoints and the WebSocket snapshot, so both return the same shape.
def _row_to_feedback(r) -> Feedback:
    return Feedback(
        created_at=_jsonable(r[0]),
        session_id=r[1],
        skill_name=r[2],
        agent=r[3],
        score=r[4],
        comment=r[5],
        request_id=r[6],
    )


def _row_to_transcript(r) -> Transcript:
    return Transcript(
        created_at=_jsonable(r[0]),
        session_id=r[1],
        skill_name=r[2],
        agent=r[3],
        schema_version=r[4],
        atif=r[5] if isinstance(r[5], dict) else json.loads(r[5]),
        request_id=r[6],
    )


# These delegate to the configured read adapter (see read_adapters/); the SQL lives
# there. Kept as thin module functions so the endpoints, the snapshot builder, and
# the tests share one call surface.
def _select_feedback(limit: int) -> list[tuple]:
    return app.state.read.select_feedback(limit)


def _select_transcript(limit: int) -> list[tuple]:
    return app.state.read.select_transcript(limit)


def _select_transcripts_by_ids(request_ids: list, session_ids: list) -> list[tuple]:
    return app.state.read.select_transcripts_by_ids(request_ids, session_ids)


def _select_transcripts_for(feedback_rows: list[tuple]) -> list[tuple]:
    """Transcripts belonging to the given feedback rows, matched by request_id/session_id.

    The dashboard links each feedback row to its trajectory by these keys. Fetching
    "the newest N transcripts" instead would drift out of step with the shown feedback
    (any rating left without a stored transcript widens the gap), so rows would show no
    trajectory even though one exists. Selecting by the shown rows' keys keeps them aligned.
    """
    request_ids = [r[6] for r in feedback_rows if r[6]]
    session_ids = [r[1] for r in feedback_rows if r[1]]
    return _select_transcripts_by_ids(request_ids, session_ids)


def _select_top_skills(limit: int) -> list[dict]:
    return app.state.read.select_top_skills(limit)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.read = get_read_adapter()
    # One broadcaster fans snapshots to all clients, so DB load tracks writes, not viewers.
    broadcaster = asyncio.create_task(_broadcaster()) if WS_ENABLED else None
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

app = FastAPI(title="ratexp-app-be", version="1.0.0", lifespan=lifespan, **_docs_kwargs)

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
    """What the UI needs to render the filter box for the active read source:
    whether the /query box is on, and the source's query language + an example."""
    read = app.state.read
    return {
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
    effective = LIST_MAX_LIMIT if full else limit
    try:
        rows = _select_feedback(effective)
    except Exception as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"db error: {e!r}") from e
    return [_row_to_feedback(r) for r in rows]


@app.get("/transcript")
def list_transcript(
    limit: int = Query(LIST_VIEW_LIMIT, ge=1, le=LIST_MAX_LIMIT),
    full: bool = False,
) -> list[Transcript]:
    # full=true (the dashboard's Download) returns every transcript up to the hard ceiling.
    effective = LIST_MAX_LIMIT if full else limit
    try:
        rows = _select_transcript(effective)
    except Exception as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"db error: {e!r}") from e
    return [_row_to_transcript(r) for r in rows]


@app.get("/stats/top-skills")
def top_skills(limit: int = Query(TOP_SKILLS_LIMIT, ge=1, le=LIST_MAX_LIMIT)) -> dict:
    """Most-rated skills with their good/bad tally, for the "Top skills" panel."""
    try:
        skills = _select_top_skills(limit)
    except Exception as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"db error: {e!r}") from e
    return {"skills": skills}


@app.get("/snapshot")
def snapshot() -> dict:
    """The dashboard's whole initial view in one call: feedback + their transcripts + stats.

    Same shape and correlation as the live WebSocket snapshot, so the first paint and
    later live updates agree and every row with a trajectory shows it.
    """
    try:
        return _build_snapshot()
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

    # The adapter validates + caps + runs the query in its language, newest-first
    # trimming (and the Download single-skill rule) happen in Python below.
    try:
        columns, rows = app.state.read.run_query(req.query, QUERY_MAX_ROWS, QUERY_TIMEOUT_MS)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"query error: {e}") from e
    except Exception as e:
        # Most other failures here are the user's query, so surface as 400, not 503.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"query error: {e!r}") from e

    result = [dict(zip(columns, (_jsonable(v) for v in row), strict=False)) for row in rows]
    fetched_truncated = len(rows) >= QUERY_MAX_ROWS
    if req.full:
        # Download: single skill -> all of it (newest first); else the most-recent view.
        result, truncated = _apply_download_rule(result, fetched_truncated)
    else:
        # Filter view: newest first, capped to the view (or an explicit, smaller limit).
        view_cap = LIST_VIEW_LIMIT if req.limit is None else max(1, min(req.limit, QUERY_MAX_ROWS))
        result, truncated = _most_recent(result, view_cap, fetched_truncated)

    # Carry the shown rows' own trajectories so the filtered table resolves them itself,
    # rather than borrowing the live preview's index (which only holds the newest rows).
    # Skipped for Download (full=true): that path fetches every transcript separately.
    transcripts: list[dict] = []
    if not req.full:
        req_ids = [r["request_id"] for r in result if r.get("request_id")]
        sess_ids = [r["session_id"] for r in result if r.get("session_id")]
        transcripts = [
            _row_to_transcript(t).model_dump()
            for t in _select_transcripts_by_ids(req_ids, sess_ids)
        ]

    return {
        "columns": columns,
        "rows": result,
        "transcripts": transcripts,
        "row_count": len(result),
        "truncated": truncated,
    }


# The dashboard opens /ws and gets a full snapshot on every change. One broadcaster
# does one DB read per interval and fans it out, so cost scales with writes, not viewers.
class Hub:
    """Tracks connected dashboards and pushes a message to all of them."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def add(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.add(ws)

    async def remove(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    @property
    def empty(self) -> bool:
        return not self._clients

    async def broadcast(self, message: dict) -> None:
        async with self._lock:
            targets = list(self._clients)
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)  # send failed - the socket is gone
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.discard(ws)


hub = Hub()


def _build_snapshot() -> dict:
    """The whole live view in one message, in the same shapes the HTTP endpoints return.

    Transcripts are the ones belonging to the shown feedback (not just the newest),
    so every row that has a trajectory shows it.
    """
    feedback_rows = _select_feedback(LIST_VIEW_LIMIT)
    transcript_rows = _select_transcripts_for(feedback_rows)
    return {
        "type": "snapshot",
        "feedback": [_row_to_feedback(r).model_dump() for r in feedback_rows],
        "transcripts": [_row_to_transcript(r).model_dump() for r in transcript_rows],
        "stats": _select_top_skills(TOP_SKILLS_LIMIT),
    }


def _change_signature() -> tuple:
    """A cheap fingerprint of the tables so the broadcaster can skip unchanged data."""
    return app.state.read.change_signature()


async def _broadcaster() -> None:
    interval = WS_BROADCAST_INTERVAL_MS / 1000
    last_sig: tuple | None = None
    while True:
        await asyncio.sleep(interval)
        if hub.empty:
            continue  # nobody watching - don't touch the DB
        try:
            sig = await asyncio.to_thread(_change_signature)
        except Exception:
            continue  # transient DB hiccup; try again next interval
        if sig == last_sig:
            continue  # no new data since the last push
        last_sig = sig
        try:
            snapshot = await asyncio.to_thread(_build_snapshot)
        except Exception:
            continue
        await hub.broadcast(snapshot)


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
        await websocket.send_json(await asyncio.to_thread(_build_snapshot))
        while True:
            await websocket.receive_text()  # keepalive; content ignored
    except WebSocketDisconnect:
        pass
    finally:
        await hub.remove(websocket)


# Serve the built UI from the API origin; mounted last so API routes win. Absent in local dev.
if _STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="dashboard")
