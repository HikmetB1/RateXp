"""phoenix - an Arize Phoenix project, over Phoenix's REST span API.

Phoenix stores OpenTelemetry spans, so a rating and a transcript each become one
span in the configured project, carrying the record on ``ratexp.*`` attributes.
The span is POSTed as JSON to ``<endpoint>/v1/projects/<project>/spans`` with
urllib - stdlib only, so this destination adds no dependency to core. Phoenix's
own SDK exports over OTLP instead, which batches in the background and would
report success before Phoenix has seen the record, breaking the fan-out's
at-least-one rule (see ../dispatch_to_adapters.py).

The span id is derived from the record's ``request_id``, so a hook that retries
posts the same id twice and Phoenix answers ``400 duplicate`` - the same
de-duplication ``ON CONFLICT (request_id) DO NOTHING`` gives the PostgreSQL
destination, and why that answer counts as stored here.

Read back by app's ``modules/read/adapters/read_from_phoenix.py``.
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from urllib.parse import quote

_SPANS_PATH = "/v1/projects/{project}/spans"
# PHOENIX_COLLECTOR_ENDPOINT is often copied with the OTLP path already on it.
_OTLP_TRACES_SUFFIX = "/v1/traces"
_SCORE_LABELS = {1: "good", 2: "bad"}


def _trace_and_span_id(seed: str | None) -> tuple[str, str]:
    """A (trace_id, span_id) pair - 32 and 16 hex characters, as Phoenix wants them.

    The same seed always gives the same pair, which is what makes a retry a
    duplicate rather than a second rating. A record with no ``request_id`` has
    nothing to de-duplicate on, so it gets a fresh pair.
    """
    digest = hashlib.sha256((seed or uuid.uuid4().hex).encode()).hexdigest()
    return digest[:32], digest[32:48]


def _iso_utc(value) -> str:
    """Phoenix rejects a timestamp without a timezone, so fall back to now in UTC."""
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        moment = datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.isoformat()


def _compact(attributes: dict) -> dict:
    return {k: v for k, v in attributes.items() if v is not None}


def _is_already_stored(error: urllib.error.HTTPError) -> bool:
    """True when Phoenix refused the post only because it already has that span id."""
    try:
        refusal = json.loads(error.read().decode())
    except (ValueError, OSError):
        return False
    return bool(refusal.get("total_duplicates")) and not refusal.get("total_invalid")


class PhoenixWriteAdapter:
    def __init__(self, endpoint: str, api_key: str, project: str, *, timeout: float = 10.0) -> None:
        if not endpoint:
            raise RuntimeError("phoenix needs a collector endpoint")
        if not api_key:
            raise RuntimeError("phoenix needs an api key")
        if not project:
            raise RuntimeError("phoenix needs a project name")
        self.name = "phoenix"
        base = endpoint.rstrip("/").removesuffix(_OTLP_TRACES_SUFFIX).rstrip("/")
        self._url = base + _SPANS_PATH.format(project=quote(project, safe=""))
        self._api_key = api_key
        self._timeout = timeout

    def _post_span(self, span: dict) -> None:
        request = urllib.request.Request(
            self._url,
            data=json.dumps({"data": [span]}).encode(),
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                accepted = json.loads(response.read().decode() or "{}")
        except urllib.error.HTTPError as error:
            if error.code == 400 and _is_already_stored(error):
                return
            raise
        if not accepted.get("total_queued"):
            raise RuntimeError(f"phoenix queued no span: {accepted}")

    def _span(self, record_type: str, span_kind: str, record, attributes: dict) -> dict:
        trace_id, span_id = _trace_and_span_id(
            f"{record_type}:{record.request_id}" if record.request_id else None
        )
        at = _iso_utc(record.created_at)
        return {
            "name": f"ratexp.{record_type}",
            "context": {"trace_id": trace_id, "span_id": span_id},
            "span_kind": span_kind,
            # A record is a point in time, not a span of work, so it has no duration.
            "start_time": at,
            "end_time": at,
            "status_code": "OK",
            "attributes": _compact(
                {
                    "ratexp.record_type": record_type,
                    "ratexp.session_id": record.session_id,
                    "ratexp.skill_name": record.skill_name,
                    "ratexp.agent": record.agent,
                    "ratexp.request_id": record.request_id,
                    **attributes,
                }
            ),
        }

    def write_feedback(self, record) -> None:
        self._post_span(
            # A rating judges a run, which is the work Phoenix's EVALUATOR kind names.
            self._span(
                "feedback",
                "EVALUATOR",
                record,
                {
                    "ratexp.eval_name": record.eval_name,
                    "ratexp.score": record.score,
                    "ratexp.rating": _SCORE_LABELS.get(record.score, "unrated"),
                    "ratexp.comment": record.comment,
                },
            )
        )

    def write_transcript(self, record) -> None:
        self._post_span(
            self._span(
                "transcript",
                "AGENT",
                record,
                {
                    "ratexp.schema_version": record.schema_version,
                    # core already caps a stored trajectory (max_transcript_bytes), so
                    # this goes in whole and always parses back as JSON on the read side.
                    "ratexp.atif": json.dumps(record.atif, ensure_ascii=False),
                },
            )
        )

    def close(self) -> None:
        """Nothing to release - every write is one request, with nothing held open."""
