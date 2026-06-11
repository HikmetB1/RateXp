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
    # Truthy check (not `is not None`) so an empty value - e.g. an unset
    # RATEXP_CORS_ORIGINS injected as "" by compose - behaves like absent.
    if CORS_ORIGINS_RAW:
        return [o.strip() for o in CORS_ORIGINS_RAW.split(",") if o.strip()]
    if ENV in ("", "local"):
        return ["*"]
    raise RuntimeError(
        f"RATEXP_ENV={ENV!r} requires RATEXP_CORS_ORIGINS to be set "
        "(comma-separated list of allowed origins)."
    )


# Resolved once and shared by both the CORS middleware (HTTP) and the WebSocket
# origin check (CORS middleware doesn't apply to WebSocket handshakes).
ALLOWED_ORIGINS = _resolve_cors_origins()

# Write/DDL keywords rejected anywhere in a /query body. The read-only
# transaction is the real guard; this denylist is defense-in-depth that also
# catches data-modifying CTEs (e.g. WITH x AS (DELETE ...) ...).
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


# --- Shared reads -------------------------------------------------------------
# These back both the HTTP list/stats endpoints and the WebSocket snapshot, so
# the dashboard sees exactly the same shape whether it polls once on load or
# receives a live push.


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
    # One shared broadcaster fans live snapshots out to every connected
    # dashboard, so write volume - not viewer count - drives DB load.
    broadcaster = asyncio.create_task(_broadcaster()) if WS_ENABLED else None
    try:
        yield
    finally:
        if broadcaster is not None:
            broadcaster.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await broadcaster
        app.state.pool.close()


app = FastAPI(title="ratexp-app-be", version="1.0.0", lifespan=lifespan)

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
    # Default returns the small dashboard view (list_view_limit). full=true - used
    # by the dashboard's "Download CSV" - returns everything up to the hard ceiling.
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
    # Default returns the small dashboard view (list_view_limit). full=true - used
    # by the dashboard's "Download CSV" - returns every transcript up to the hard
    # ceiling so the export can attach each row's conversation.
    effective = LIST_MAX_LIMIT if full else limit
    try:
        rows = _select_transcript(effective)
    except Exception as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"db error: {e!r}") from e
    return [_row_to_transcript(r) for r in rows]


@app.get("/stats/top-skills")
def top_skills(limit: int = Query(TOP_SKILLS_LIMIT, ge=1, le=LIST_MAX_LIMIT)) -> dict:
    """Most-rated skills with their good/bad tally - powers the dashboard's
    "Top skills" panel. Aggregates the whole feedback table, ordered by number of
    ratings, capped at `limit` (default top_skills_limit from config.yaml)."""
    try:
        skills = _select_top_skills(limit)
    except Exception as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"db error: {e!r}") from e
    return {"skills": skills}


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
    # full=true (the dashboard's "Download CSV") returns everything up to the hard
    # row cap; otherwise the default is the small dashboard view (list_view_limit).
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
                # SET takes a literal, not a bound param; QUERY_TIMEOUT_MS is an
                # int from config, so int() makes the inlining injection-safe.
                cur.execute(f"SET LOCAL statement_timeout = {int(QUERY_TIMEOUT_MS)}")
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute(wrapped, (cap,))
                columns = [d.name for d in cur.description] if cur.description else []
                rows = cur.fetchall()
    except HTTPException:
        raise
    except Exception as e:
        # Most failures here are the user's SQL (bad syntax, unknown column), so
        # surface them as 400 so they can fix the query rather than a 503.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"query error: {e!r}") from e

    return {
        "columns": columns,
        "rows": [dict(zip(columns, (_jsonable(v) for v in row), strict=False)) for row in rows],
        "row_count": len(rows),
        "truncated": len(rows) >= cap,
    }


# --- Live updates (WebSocket) -------------------------------------------------
# The dashboard opens /ws and receives a full "snapshot" whenever the data
# changes. A single shared broadcaster does one DB read per interval and fans it
# out to every connected client, so cost scales with write volume, not viewers.


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
    """The dashboard's whole live view in one message - same shapes the HTTP
    endpoints return, so the frontend applies it with identical code."""
    return {
        "type": "snapshot",
        "feedback": [_row_to_feedback(r).model_dump() for r in _select_feedback(LIST_VIEW_LIMIT)],
        "transcripts": [
            _row_to_transcript(r).model_dump() for r in _select_transcript(LIST_VIEW_LIMIT)
        ],
        "stats": _select_top_skills(TOP_SKILLS_LIMIT),
    }


def _change_signature() -> tuple:
    """A cheap fingerprint of the tables so the broadcaster can skip work (and
    avoid needless client re-renders) when nothing has changed."""
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
    # CORS middleware doesn't guard WebSocket handshakes, so enforce the same
    # allowlist here. "*" (local default) lets any origin connect.
    if "*" in ALLOWED_ORIGINS:
        return True
    origin = websocket.headers.get("origin")
    return bool(origin) and origin in ALLOWED_ORIGINS


@app.websocket("/ws")
async def ws_feed(websocket: WebSocket) -> None:
    """Live feed: pushes a snapshot on connect, then on every change. Incoming
    client messages are ignored - this channel is server -> dashboard only."""
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


# Serve the built dashboard from the same origin as the API (production image).
# Mounted last so the API routes above take precedence; absent in local dev,
# where the Vite dev server serves the UI instead.
if _STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="dashboard")
