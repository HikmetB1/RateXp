"""The interface every destination adapter implements.

A write adapter is one place a submission can be sent. core validates and redacts
a record once, then hands it to every enabled adapter (see dispatch.py). Write
adapters are independent and best-effort: one failing never stops the others or
the request. Each concrete destination lives in its own file:

- ``app_be_psql.py`` - RateXp's own DB (the one the live dashboard reads).
- ``custom_psql.py`` - an adopter's own PostgreSQL.
- ``app_be_dynatrace.py`` - RateXp's Dynatrace tenant (OpenTelemetry/OTLP).
- ``custom_dynatrace.py`` - an adopter's own Dynatrace tenant (OTLP).
- ``bluebox.py`` - a Bluebox workspace (OTLP). Write-only: Bluebox has no query
  language, so it has no counterpart in app-be's read_adapters/.

The two shared bases they build on live in ``utils/`` (``utils/postgres.py`` ->
``PostgresWriteAdapter``, ``utils/dynatrace.py`` -> ``DynatraceWriteAdapter``). To add
a destination: implement this interface and register it in ``build_write_adapters``
(``__init__.py``), keyed by a name in config.yaml ``write_adapters``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from models import Feedback, Transcript


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
