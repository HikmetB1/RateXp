"""The interface every destination adapter implements.

A write adapter is one place a submission can be sent. core validates and redacts
a record once, then hands it to every enabled adapter (see
../dispatch_to_adapters.py). Write adapters are independent: one failing never
stops the others, and the request still succeeds as long as at least one adapter
accepted the record. Each concrete destination lives in its own file:

- ``write_to_app_be_psql.py`` - RateXp's own DB (the one the live dashboard reads).
- ``write_to_custom_psql.py`` - an adopter's own PostgreSQL.
- ``write_to_app_be_dynatrace.py`` - RateXp's Dynatrace tenant (OpenTelemetry/OTLP).
- ``write_to_custom_dynatrace.py`` - an adopter's own Dynatrace tenant (OTLP).
- ``write_to_bluebox.py`` - a Bluebox workspace (OTLP). Write-only: Bluebox has no
  query language, so it has no counterpart in app's modules/read/.
- ``write_to_phoenix.py`` - an Arize Phoenix project, one span per record over
  Phoenix's REST API.

The two shared bases they build on are ``write_to_postgres.py`` ->
``PostgresWriteAdapter`` and ``write_to_dynatrace.py`` -> ``DynatraceWriteAdapter``.
To add a destination: implement this interface and register it in
``_build_one`` (../dispatch_to_adapters.py), keyed by a name in config.yaml
``write_adapters``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from api.record_schemas import Feedback, Transcript


@runtime_checkable
class WriteAdapter(Protocol):
    # Stable identifier used in logs and config (e.g. "app_be_psql").
    name: str

    def write_feedback(self, record: Feedback) -> None:
        """Send one rating to this destination. May raise; the caller isolates it."""
        ...

    def write_transcript(self, record: Transcript) -> None:
        """Send one transcript to this destination. May raise; the caller isolates it."""
        ...

    def close(self) -> None:
        """Release resources / flush buffers (called on server shutdown)."""
        ...
