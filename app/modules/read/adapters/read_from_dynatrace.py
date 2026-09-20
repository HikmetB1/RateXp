"""Shared DQL read logic for the Dynatrace read adapters (app_be_dynatrace, custom_dynatrace).

Queries Dynatrace with DQL (execute + poll) and maps log records to the same row
shapes the PostgreSQL adapter returns, so ``api/`` stays unchanged. Stdlib only.

The filter box speaks **DQL** here (``query_language = "DQL"``): ``run_query`` runs the
user's DQL read query, row-capped, and normalizes the columns for the table. Inherent
limits (Dynatrace is a log store):
- Transcripts carry only the truncated ``ratexp.atif`` attribute, so full trajectories
  don't reconstruct; a stub atif is returned for those.
- Each read is an async DQL query, so the live feed costs more than a SQL count.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode

_EXECUTE_PATH = "/platform/storage/query/v1/query:execute"
_POLL_PATH = "/platform/storage/query/v1/query:poll"
_LOOKBACK = "-30d"  # DQL fetch timeframe the dashboard reads over
_POLL_ATTEMPTS = 20
_POLL_INTERVAL = 0.5
# Fields we pull for each row shape (dotted OTLP attribute names).
_FEEDBACK_FIELDS = (
    "timestamp, ratexp.session_id, ratexp.skill_name, ratexp.agent, "
    "ratexp.score, ratexp.comment, ratexp.request_id"
)
_TRANSCRIPT_FIELDS = (
    "timestamp, ratexp.session_id, ratexp.skill_name, ratexp.agent, "
    "ratexp.schema_version, ratexp.atif, ratexp.request_id"
)


def _iso_seconds(ts):
    """Trim a Dynatrace nanosecond ISO timestamp to whole seconds + Z (psql's shape)."""
    if not isinstance(ts, str):
        return ts
    return ts.split(".", 1)[0].rstrip("Z") + "Z"


def _int_or_none(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _dql_str(value) -> str:
    """Quote a value as a DQL string literal (escapes backslashes and quotes)."""
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _norm_col(name: str) -> str:
    """Map a DQL result column to the dashboard's shape: strip the ratexp. prefix and
    rename timestamp -> created_at, so feedback-record queries render in the table
    (and the transcript lookup finds request_id / session_id)."""
    if name == "timestamp":
        return "created_at"
    return name.removeprefix("ratexp.")


class DynatraceReadAdapter:
    query_language = "DQL"
    query_example = (
        'fetch logs | filter ratexp.record_type == "feedback" and ratexp.skill_name == "..."'
    )

    def __init__(self, name: str, query_url: str, token: str) -> None:
        if not query_url:
            raise RuntimeError(f"{name} read adapter needs a query URL (query_url_env)")
        if not token:
            raise RuntimeError(f"{name} read adapter needs a token (token_env)")
        self.name = name
        self._base = query_url.rstrip("/")
        self._token = token

    # ------------------------------------------------------------------
    # DQL client (execute, then poll until the query finishes)
    # ------------------------------------------------------------------
    def _request(self, path: str, *, method: str, body=None, params=None):
        url = self._base + path + ("?" + urlencode(params) if params else "")
        headers = {"Authorization": f"Api-Token {self._token}"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())

    def _dql(self, query: str) -> list[dict]:
        resp = self._request(_EXECUTE_PATH, method="POST", body={"query": query})
        if resp.get("state") == "SUCCEEDED":
            return resp.get("result", {}).get("records", []) or []
        token = resp.get("requestToken")
        for _ in range(_POLL_ATTEMPTS):
            poll = self._request(_POLL_PATH, method="GET", params={"request-token": token})
            if poll.get("state") == "SUCCEEDED":
                return poll.get("result", {}).get("records", []) or []
            time.sleep(_POLL_INTERVAL)
        raise TimeoutError("Dynatrace DQL query did not complete in time")

    # ------------------------------------------------------------------
    # ReadAdapter interface
    # ------------------------------------------------------------------
    def select_feedback(self, limit: int) -> list[tuple]:
        recs = self._dql(
            f'fetch logs, from:{_LOOKBACK} | filter ratexp.record_type == "feedback" '
            f"| sort timestamp desc | limit {int(limit)} | fields {_FEEDBACK_FIELDS}"
        )
        return [
            (
                _iso_seconds(r.get("timestamp")),
                r.get("ratexp.session_id"),
                r.get("ratexp.skill_name"),
                r.get("ratexp.agent"),
                _int_or_none(r.get("ratexp.score")),
                r.get("ratexp.comment"),
                r.get("ratexp.request_id"),
            )
            for r in recs
        ]

    def select_transcript(self, limit: int) -> list[tuple]:
        recs = self._dql(
            f'fetch logs, from:{_LOOKBACK} | filter ratexp.record_type == "transcript" '
            f"| sort timestamp desc | limit {int(limit)} | fields {_TRANSCRIPT_FIELDS}"
        )
        return [self._transcript_row(r) for r in recs]

    def select_transcripts_by_ids(self, request_ids: list, session_ids: list) -> list[tuple]:
        if not request_ids and not session_ids:
            return []
        clauses = []
        if request_ids:
            clauses.append(
                "in(ratexp.request_id, " + ", ".join(_dql_str(x) for x in request_ids) + ")"
            )
        if session_ids:
            clauses.append(
                "in(ratexp.session_id, " + ", ".join(_dql_str(x) for x in session_ids) + ")"
            )
        where = " or ".join(clauses)
        recs = self._dql(
            f'fetch logs, from:{_LOOKBACK} | filter ratexp.record_type == "transcript" '
            f"and ({where}) | sort timestamp desc | fields {_TRANSCRIPT_FIELDS}"
        )
        return [self._transcript_row(r) for r in recs]

    def _transcript_row(self, r: dict) -> tuple:
        raw = r.get("ratexp.atif")
        try:
            atif = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(atif, dict):
                raise ValueError
        except (ValueError, TypeError):
            # Truncated in Dynatrace -> not valid JSON. Return a stub the UI can render.
            atif = {
                "schema_version": r.get("ratexp.schema_version"),
                "steps": [],
                "dynatrace_truncated": True,
            }
        return (
            _iso_seconds(r.get("timestamp")),
            r.get("ratexp.session_id"),
            r.get("ratexp.skill_name"),
            r.get("ratexp.agent"),
            r.get("ratexp.schema_version"),
            atif,
            r.get("ratexp.request_id"),
        )

    def select_top_skills(self, limit: int) -> list[dict]:
        recs = self._dql(
            f'fetch logs, from:{_LOOKBACK} | filter ratexp.record_type == "feedback" '
            "and isNotNull(ratexp.skill_name) "
            "| summarize total=count(), good=countIf(ratexp.score == 1), "
            "bad=countIf(ratexp.score == 2), by:{skill_name=ratexp.skill_name} "
            f"| sort total desc, skill_name asc | limit {int(limit)}"
        )
        return [
            {
                "skill_name": r.get("skill_name"),
                "total": _int_or_none(r.get("total")) or 0,
                "good": _int_or_none(r.get("good")) or 0,
                "bad": _int_or_none(r.get("bad")) or 0,
            }
            for r in recs
        ]

    def run_query(
        self, query: str, max_rows: int, timeout_ms: int
    ) -> tuple[list[str], list[tuple]]:
        # DQL is read-only by nature; guard it starts with a fetch/read verb, then cap rows.
        cleaned = query.strip()
        if not cleaned:
            raise ValueError("empty query")
        if not re.match(r"(?i)^(fetch|data|timeseries|describe)\b", cleaned):
            raise ValueError(
                "only DQL read queries are allowed (start with fetch / data / timeseries)"
            )
        records = self._dql(f"{cleaned} | limit {int(max_rows)}")
        if not records:
            return [], []
        # Normalize column names so feedback-record results render in the dashboard
        # table just like the preview does (created_at, skill_name, score, ...).
        raw = list(records[0].keys())
        columns = [_norm_col(c) for c in raw]
        rows = [
            tuple(
                _iso_seconds(rec.get(c))
                if c == "timestamp"
                else _int_or_none(rec.get(c))
                if c == "ratexp.score"
                else rec.get(c)
                for c in raw
            )
            for rec in records
        ]
        return columns, rows

    def change_signature(self) -> tuple:
        recs = self._dql(
            f'fetch logs, from:{_LOOKBACK} | filter ratexp.record_type == "feedback" '
            'or ratexp.record_type == "transcript" '
            "| summarize c=count(), maxts=max(timestamp), by:{ratexp.record_type}"
        )
        return tuple(
            sorted((r.get("ratexp.record_type"), r.get("c"), r.get("maxts")) for r in recs)
        )

    def close(self) -> None:
        pass
