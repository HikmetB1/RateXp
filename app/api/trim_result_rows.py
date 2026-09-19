"""How many rows a response returns, and in what order.

The Download rule is judged here, server-side over the whole result, not from the rows
already on screen - the preview holds only the newest few, so deciding it there would
export the wrong set.
"""

from __future__ import annotations

from datetime import datetime

from load_config import LIST_VIEW_LIMIT


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

    A result that resolves to a single skill is exported in full (newest first); anything
    else - more than one skill, or a shape without a usable skill_name column - is trimmed
    to the most recent view-limit rows.
    """
    skills = {r.get("skill_name") for r in rows}
    single_skill = (
        bool(rows)
        and "skill_name" in rows[0]
        and skills == {rows[0]["skill_name"]}
        and None not in skills
    )
    return most_recent(rows, None if single_skill else LIST_VIEW_LIMIT, fetched_truncated)
