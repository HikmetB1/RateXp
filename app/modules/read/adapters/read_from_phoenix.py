"""phoenix - an Arize Phoenix project, read over Phoenix's REST span API.

Reads back the spans core's ``modules/write/adapters/write_to_phoenix.py`` posted
and maps them to the same row shapes the PostgreSQL adapter returns, so ``api/``
stays unchanged. Stdlib only.

The filter box speaks **Phoenix filters** (``query_language``): a line of
``key:value`` pairs, which is what the REST API itself takes. Phoenix offers no
query language over REST, so there is nothing richer to pass through, and a
filter can only ever read. Inherent limits, all from that same API:

- It returns spans newest-*ingested* first and takes no sort parameter, so rows
  are re-sorted by timestamp here: "the newest 10" is the newest 10 of the last
  10 ingested.
- It cannot aggregate or match one attribute against a list, so the top-skills
  tally and the transcript lookup pull a window of spans and finish the work
  here, capped at ``list_max_limit``.
"""

from __future__ import annotations

import json
import urllib.request
from urllib.parse import quote, urlencode

from load_config import LIST_MAX_LIMIT

_SPANS_PATH = "/v1/projects/{project}/spans"
_OTLP_TRACES_SUFFIX = "/v1/traces"
# Every record field rides on an attribute under this prefix; the dashboard's
# columns are the same names without it.
_PREFIX = "ratexp."
# Phoenix's own ceiling on ?limit - asking for more is rejected outright.
_MAX_SPANS_PER_REQUEST = 1000
# Filter-box keys that name part of the span itself rather than a ratexp attribute.
_SPAN_KEYS = ("name", "span_kind", "status_code", "trace_id", "span_id", "parent_id")


def _iso_seconds(value):
    """Trim Phoenix's ``+00:00`` timestamp to whole seconds + Z (psql's shape)."""
    if not isinstance(value, str):
        return value
    return value.split(".", 1)[0].removesuffix("+00:00").removesuffix("Z") + "Z"


def _atif(raw, schema_version):
    """The trajectory is stored whole, so anything unparseable came from elsewhere."""
    try:
        trajectory = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        trajectory = None
    if not isinstance(trajectory, dict):
        return {"schema_version": schema_version, "steps": []}
    return trajectory


def _parse_filters(query: str, max_rows: int) -> dict:
    """``record_type:feedback skill_name:demo limit:20`` -> Phoenix's query params.

    Anything that is not ``key:value`` raises ValueError, which /query turns into
    a 400 with the message below, rather than silently reading everything.
    """
    tokens = query.split()
    if not tokens:
        raise ValueError("empty query")
    params: dict = {"limit": max_rows}
    attributes: list[str] = []
    for token in tokens:
        key, _, value = token.partition(":")
        if not key or not value:
            raise ValueError(f"{token!r} is not key:value - try record_type:feedback")
        if key == "limit":
            if not value.isdigit():
                raise ValueError("limit takes a number, e.g. limit:50")
            params["limit"] = min(int(value), max_rows)
        elif key in _SPAN_KEYS:
            params[key] = value
        else:
            attributes.append(f"{_PREFIX}{key}:{value}")
    if attributes:
        params["attribute"] = attributes
    return params


class PhoenixReadAdapter:
    query_language = "Phoenix filters"
    query_example = "record_type:feedback skill_name:... limit:50"

    def __init__(self, endpoint: str, api_key: str, project: str) -> None:
        if not endpoint:
            raise RuntimeError("phoenix read adapter needs a collector endpoint (endpoint_env)")
        if not api_key:
            raise RuntimeError("phoenix read adapter needs an api key (api_key_env)")
        if not project:
            raise RuntimeError("phoenix read adapter needs a project name (project_env)")
        self.name = "phoenix"
        base = endpoint.rstrip("/").removesuffix(_OTLP_TRACES_SUFFIX).rstrip("/")
        self._url = base + _SPANS_PATH.format(project=quote(project, safe=""))
        self._api_key = api_key

    # ------------------------------------------------------------------
    # Phoenix client
    # ------------------------------------------------------------------
    def _spans(self, params: dict, timeout: float = 30.0) -> list[dict]:
        request = urllib.request.Request(
            self._url + "?" + urlencode(params, doseq=True),
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode()).get("data") or []

    def _newest_first(self, record_type: str, limit: int) -> list[dict]:
        spans = self._spans(
            {
                "limit": max(1, min(int(limit), _MAX_SPANS_PER_REQUEST)),
                "attribute": [f"{_PREFIX}record_type:{record_type}"],
            }
        )
        return sorted(spans, key=lambda span: span.get("start_time") or "", reverse=True)

    # ------------------------------------------------------------------
    # ReadAdapter interface
    # ------------------------------------------------------------------
    def select_feedback(self, limit: int) -> list[tuple]:
        return [self._feedback_row(span) for span in self._newest_first("feedback", limit)]

    def select_transcript(self, limit: int) -> list[tuple]:
        return [self._transcript_row(span) for span in self._newest_first("transcript", limit)]

    def select_transcripts_by_ids(self, request_ids: list, session_ids: list) -> list[tuple]:
        wanted_requests = {x for x in request_ids if x}
        wanted_sessions = {x for x in session_ids if x}
        if not wanted_requests and not wanted_sessions:
            return []
        # Phoenix ANDs its attribute filters and has no "one of", so the match on
        # either id list happens here, over a window of the newest transcripts.
        return [
            self._transcript_row(span)
            for span in self._newest_first("transcript", LIST_MAX_LIMIT)
            if (span.get("attributes") or {}).get(f"{_PREFIX}request_id") in wanted_requests
            or (span.get("attributes") or {}).get(f"{_PREFIX}session_id") in wanted_sessions
        ]

    def select_top_skills(self, limit: int) -> list[dict]:
        tally: dict[str, dict] = {}
        for span in self._newest_first("feedback", LIST_MAX_LIMIT):
            attributes = span.get("attributes") or {}
            skill_name = attributes.get(f"{_PREFIX}skill_name")
            counts = tally.setdefault(
                skill_name, {"skill_name": skill_name, "total": 0, "good": 0, "bad": 0}
            )
            counts["total"] += 1
            if attributes.get(f"{_PREFIX}score") == 1:
                counts["good"] += 1
            elif attributes.get(f"{_PREFIX}score") == 2:
                counts["bad"] += 1
        ranked = sorted(tally.values(), key=lambda row: (-row["total"], row["skill_name"] or ""))
        return ranked[:limit]

    def run_query(
        self, query: str, max_rows: int, timeout_ms: int
    ) -> tuple[list[str], list[tuple]]:
        spans = self._spans(_parse_filters(query, max_rows), timeout=timeout_ms / 1000)
        if not spans:
            return [], []
        # Name the columns the way the preview does (created_at, skill_name, score,
        # ...) so a filtered result renders in the same table.
        found = [
            {"created_at": _iso_seconds(span.get("start_time"))}
            | {
                key.removeprefix(_PREFIX): value
                for key, value in sorted((span.get("attributes") or {}).items())
            }
            for span in spans
        ]
        columns = list(found[0])
        return columns, [tuple(row.get(column) for column in columns) for row in found]

    def change_signature(self) -> tuple:
        # Newest-ingested first means the first span changes whenever anything
        # lands, so one span is the whole fingerprint - no count to pay for.
        spans = self._spans({"limit": 1})
        if not spans:
            return ()
        return (spans[0].get("id"), spans[0].get("start_time"))

    def close(self) -> None:
        """Nothing to release - every read is one request, with nothing held open."""

    # ------------------------------------------------------------------
    # Span -> row
    # ------------------------------------------------------------------
    def _feedback_row(self, span: dict) -> tuple:
        attributes = span.get("attributes") or {}
        return (
            _iso_seconds(span.get("start_time")),
            attributes.get(f"{_PREFIX}session_id"),
            attributes.get(f"{_PREFIX}skill_name"),
            attributes.get(f"{_PREFIX}agent"),
            attributes.get(f"{_PREFIX}score"),
            attributes.get(f"{_PREFIX}comment"),
            attributes.get(f"{_PREFIX}request_id"),
        )

    def _transcript_row(self, span: dict) -> tuple:
        attributes = span.get("attributes") or {}
        schema_version = attributes.get(f"{_PREFIX}schema_version")
        return (
            _iso_seconds(span.get("start_time")),
            attributes.get(f"{_PREFIX}session_id"),
            attributes.get(f"{_PREFIX}skill_name"),
            attributes.get(f"{_PREFIX}agent"),
            schema_version,
            _atif(attributes.get(f"{_PREFIX}atif"), schema_version),
            attributes.get(f"{_PREFIX}request_id"),
        )
