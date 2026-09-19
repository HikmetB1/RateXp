"""Shared Dynatrace write logic (OpenTelemetry OTLP/HTTP protobuf).

``DynatraceWriteAdapter`` turns a rating/transcript into an OTLP log record and exports
it via the OpenTelemetry SDK to ``<tenant_url>/api/v2/otlp/v1/logs`` (Dynatrace
accepts protobuf there, not JSON). The concrete adapters that use it live in their
own files and differ only in which tenant + token they carry:

- ``write_to_app_be_dynatrace.py`` -> ``AppBeDynatraceWriteAdapter`` (RateXp's own tenant).
- ``write_to_custom_dynatrace.py`` -> ``CustomDynatraceWriteAdapter`` (an adopter's own tenant).

Needs the ``dynatrace-otlp`` extra (opentelemetry-sdk + otlp-proto-http),
imported lazily so core runs without it unless a Dynatrace adapter is enabled.
The SDK pipeline is built on first write; ``close`` flushes and stops it.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

_OTLP_LOGS_PATH = "/api/v2/otlp/v1/logs"
_SEVERITY_NUMBERS = {"INFO": 9, "WARN": 13, "WARNING": 13, "ERROR": 17}
# Cap the serialised trajectory attached to a transcript log so one huge
# conversation can't get the record rejected by the ingest size limit.
_MAX_ATIF_CHARS = 200_000
_SCORE_LABELS = {1: "good", 2: "bad"}


def _to_epoch_nanos(value: Any) -> int | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return int(dt.timestamp() * 1_000_000_000)
    except ValueError:
        return None


def _compact(record: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in record.items() if v is not None}


class DynatraceWriteAdapter:
    def __init__(self, name: str, tenant_url: str, token: str, *, timeout: float = 10.0) -> None:
        if not tenant_url:
            raise RuntimeError(f"{name} needs a tenant_url")
        if not token:
            raise RuntimeError(f"{name} needs a token")
        self.name = name
        self._endpoint = tenant_url.rstrip("/") + _OTLP_LOGS_PATH
        self._token = token
        self._timeout = timeout
        self._provider = None  # built lazily so importing this needs no SDK
        self._logger = None

    def _ensure_logger(self):
        if self._provider is None:
            from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
            from opentelemetry.sdk._logs import LoggerProvider
            from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
            from opentelemetry.sdk.resources import Resource

            exporter = OTLPLogExporter(
                endpoint=self._endpoint,
                headers={"Authorization": f"Api-Token {self._token}"},
                timeout=int(self._timeout),
            )
            provider = LoggerProvider(resource=Resource.create({"service.name": "ratexp-core"}))
            provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
            self._provider = provider
            self._logger = provider.get_logger("ratexp-core")
        return self._logger

    def _emit(self, log: dict[str, Any]) -> None:
        from opentelemetry._logs import SeverityNumber

        logger = self._ensure_logger()
        ts = _to_epoch_nanos(log.get("timestamp"))
        severity_text = str(log.get("severity") or "INFO").upper()
        attributes = {
            k: v
            for k, v in log.items()
            if k not in ("timestamp", "severity", "content") and v is not None
        }
        logger.emit(
            timestamp=ts,
            observed_timestamp=ts,
            severity_number=SeverityNumber(_SEVERITY_NUMBERS.get(severity_text, 9)),
            severity_text=severity_text,
            body=log.get("content"),
            attributes=attributes,
        )

    def write_feedback(self, record) -> None:
        label = _SCORE_LABELS.get(record.score, "unrated")
        self._emit(
            _compact(
                {
                    "timestamp": record.created_at,
                    "content": f"RateXp rating: {label} · skill={record.skill_name} · agent={record.agent}",
                    "severity": "INFO",
                    "log.source": "ratexp-core",
                    "ratexp.record_type": "feedback",
                    "ratexp.session_id": record.session_id,
                    "ratexp.skill_name": record.skill_name,
                    "ratexp.agent": record.agent,
                    "ratexp.score": record.score,
                    "ratexp.rating": label,
                    "ratexp.comment": record.comment,
                    "ratexp.request_id": record.request_id,
                }
            )
        )

    def write_transcript(self, record) -> None:
        atif_json = json.dumps(record.atif, ensure_ascii=False)
        truncated = len(atif_json) > _MAX_ATIF_CHARS
        self._emit(
            _compact(
                {
                    "timestamp": record.created_at,
                    "content": (
                        f"RateXp transcript · skill={record.skill_name} · "
                        f"agent={record.agent} · session={record.session_id}"
                    ),
                    "severity": "INFO",
                    "log.source": "ratexp-core",
                    "ratexp.record_type": "transcript",
                    "ratexp.session_id": record.session_id,
                    "ratexp.skill_name": record.skill_name,
                    "ratexp.agent": record.agent,
                    "ratexp.schema_version": record.schema_version,
                    "ratexp.request_id": record.request_id,
                    "ratexp.atif": atif_json[:_MAX_ATIF_CHARS] if truncated else atif_json,
                    "ratexp.atif_truncated": truncated or None,
                }
            )
        )

    def close(self) -> None:
        if self._provider is not None:
            provider = self._provider
            self._provider = None
            self._logger = None
            provider.shutdown()  # force-flushes the batch processor
