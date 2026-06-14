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
import re
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
from db import make_pool
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from models import Feedback, QueryRequest, Transcript

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

# Defense-in-depth on top of the read-only transaction; also catches data-modifying CTEs.
_FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|vacuum|merge|call|do)\b",
    re.IGNORECASE,
)


def _validate_select(sql: str) -> str:
    """Return a cleaned single SELECT statement, or raise HTTP 400."""
    cleaned = sql.strip().rstrip(";").strip()
    if not cleaned:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty query")
    if ";" in cleaned:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "only a single statement is allowed")
    if not re.match(r"(?is)^\s*(select|with)\b", cleaned):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "only SELECT queries are allowed")
    if _FORBIDDEN_SQL.search(cleaned):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "only read-only SELECT queries are allowed"
        )
    return cleaned


def _jsonable(value):
    """Match the list endpoints' wire format: datetime -> ISO8601 Z string."""
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds").replace("+00:00", "Z")
    return value


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


def _select_feedback(limit: int) -> list[tuple]:
    with app.state.pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT created_at, session_id, skill_name, agent, score, comment, request_id
            FROM feedback
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        return cur.fetchall()


def _select_transcript(limit: int) -> list[tuple]:
    with app.state.pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT created_at, session_id, skill_name, agent, schema_version, atif, request_id
            FROM transcript
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        return cur.fetchall()


def _select_transcripts_for(feedback_rows: list[tuple]) -> list[tuple]:
    """Transcripts belonging to the given feedback rows, matched by request_id/session_id.

    The dashboard links each feedback row to its trajectory by these keys. Fetching
    "the newest N transcripts" instead would drift out of step with the shown feedback
    (any rating left without a stored transcript widens the gap), so rows would show no
    trajectory even though one exists. Selecting by the shown rows' keys keeps them aligned.
    """
    request_ids = [r[6] for r in feedback_rows if r[6]]
    session_ids = [r[1] for r in feedback_rows if r[1]]
    if not request_ids and not session_ids:
        return []
    with app.state.pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT created_at, session_id, skill_name, agent, schema_version, atif, request_id
            FROM transcript
            WHERE request_id = ANY(%s) OR session_id = ANY(%s)
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (request_ids, session_ids, LIST_MAX_LIMIT),
        )
        return cur.fetchall()


def _select_top_skills(limit: int) -> list[dict]:
    with app.state.pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT skill_name,
                   COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE score = 1) AS good,
                   COUNT(*) FILTER (WHERE score = 2) AS bad
            FROM feedback
            GROUP BY skill_name
            ORDER BY total DESC, skill_name ASC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    return [{"skill_name": r[0], "total": r[1], "good": r[2], "bad": r[3]} for r in rows]


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = make_pool()
    # One broadcaster fans snapshots to all clients, so DB load tracks writes, not viewers.
    broadcaster = asyncio.create_task(_broadcaster()) if WS_ENABLED else None
    try:
        yield
    finally:
        if broadcaster is not None:
            broadcaster.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await broadcaster
        app.state.pool.close()


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
    """Run a guarded, read-only SELECT for the dashboard's filter/CSV box.

    Layered guardrails: SELECT-only + single statement (validated), wrapped in a
    row-capping subquery, and executed in a read-only transaction with a
    statement timeout - so writes are impossible and cost/volume are bounded.
    """
    if not QUERY_ENABLED:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "query endpoint disabled")

    cleaned = _validate_select(req.sql)
    # full=true exports up to the row cap; else the small view.
    if req.full:
        cap = QUERY_MAX_ROWS
    elif req.limit is None:
        cap = min(LIST_VIEW_LIMIT, QUERY_MAX_ROWS)
    else:
        cap = max(1, min(req.limit, QUERY_MAX_ROWS))
    wrapped = f"SELECT * FROM ({cleaned}) AS _q LIMIT %s"

    try:
        with app.state.pool.connection() as conn:
            with conn.transaction(), conn.cursor() as cur:
                # SET needs a literal, not a bound param; int() keeps the inlining injection-safe.
                cur.execute(f"SET LOCAL statement_timeout = {int(QUERY_TIMEOUT_MS)}")
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute(wrapped, (cap,))
                columns = [d.name for d in cur.description] if cur.description else []
                rows = cur.fetchall()
    except HTTPException:
        raise
    except Exception as e:
        # Most failures here are the user's SQL, so surface them as 400, not 503.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"query error: {e!r}") from e

    return {
        "columns": columns,
        "rows": [dict(zip(columns, (_jsonable(v) for v in row), strict=False)) for row in rows],
        "row_count": len(rows),
        "truncated": len(rows) >= cap,
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
    with app.state.pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*), max(created_at) FROM feedback")
        feedback = cur.fetchall()
        cur.execute("SELECT count(*), max(created_at) FROM transcript")
        transcript = cur.fetchall()
    return (str(feedback), str(transcript))


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
