"""How many rows a response returns, and in what order.

The Download rule is judged here, server-side over the whole result, not from the rows
already on screen - the preview holds only the newest few, so deciding it there would
export the wrong set.
"""

from __future__ import annotations

from datetime import datetime

from load_config import LIST_VIEW_LIMIT

# A Download exports in full when every row shares one of these: one skill, or one agent.
SUBJECT_COLUMNS = ("skill_name", "agent")


def jsonable(value):
    """Match the list endpoints' wire format: datetime -> ISO8601 Z string."""
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds").replace("+00:00", "Z")
    return value


def most_recent(
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


def apply_download_rule(rows: list[dict], fetched_truncated: bool) -> tuple[list[dict], bool]:
    """Decide what a full (Download) query actually returns, judged over the whole result.

    A result that resolves to a single skill or a single agent is exported in full (newest
    first); anything else - several skills across several agents, or a shape without a
    usable skill_name/agent column - is trimmed to the most recent view-limit rows.
    """
    one_subject = any(_one_value(rows, column) for column in SUBJECT_COLUMNS)
    return most_recent(rows, None if one_subject else LIST_VIEW_LIMIT, fetched_truncated)


def _one_value(rows: list[dict], column: str) -> bool:
    """True when every row carries the same, non-empty value in `column`."""
    values = {r.get(column) for r in rows}
    return bool(rows) and column in rows[0] and len(values) == 1 and None not in values
