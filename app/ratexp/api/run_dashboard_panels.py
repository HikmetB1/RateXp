"""The Dashboard view: each panel is one SQL from core's ``dashboard_for_app.yaml``, run
with the user's filters bound as named parameters; plus the dropdown values and the
filtered export with each rating's conversation.

PostgreSQL only - the panel SQL is written for it, and the other read sources draw their
dashboards in their own tools (see core/modules/dashboard/).
"""

from __future__ import annotations

from decimal import Decimal

from api.build_snapshot import display_name, row_to_transcript
from api.record_schemas import Feedback, PanelFilters
from api.trim_result_rows import jsonable
from load_config import LIST_MAX_LIMIT, LIST_VIEW_LIMIT, QUERY_TIMEOUT_MS
from modules.read.clone_dashboard_from_base import clone_dashboard

# The literal every panel's SQL carries where the shared filter fragment goes.
FILTERS_MARKER = "{filters}"


def load_dashboard() -> dict:
    """The app's dashboard - panels with their SQL, filters, download - from the YAML files.

    Read per call: two small files, and nothing is opened until the view is used.
    """
    return clone_dashboard("app")


def filter_values(read, dashboard: dict, type_: str | None) -> dict[str, list]:
    """The values for each dropdown: type, then the distinct skill, agent, eval and label of
    each label group that exist for the picked type (None or "" - all of them)."""
    params = {"type": type_ or None}
    return {
        key: [row[0] for row in read.run_dashboard_sql(sql, params, QUERY_TIMEOUT_MS)[1]]
        for key, sql in dashboard["filters"]["values"].items()
    }


def find_panel(dashboard: dict, panel_id: str) -> dict | None:
    return next((p for p in dashboard["panels"] if p["id"] == panel_id), None)


def run_panel(read, dashboard: dict, panel: dict, filters: PanelFilters) -> dict:
    """One panel's ``{"columns", "rows"}`` with the filters applied; cells JSON-ready.

    Every panel gets ``limit`` = LIST_VIEW_LIMIT, which the feedback panel's SQL uses so the
    Dashboard view's Feedback table shows as many ratings as the Query & table view.
    """
    sql = panel["sql"].replace(FILTERS_MARKER, dashboard["filters"]["sql"])
    params = {**filters.params(), "limit": LIST_VIEW_LIMIT}
    columns, rows = read.run_dashboard_sql(sql, params, QUERY_TIMEOUT_MS)
    return {"columns": columns, "rows": [[_cell(v) for v in row] for row in rows]}


def _cell(value):
    # PostgreSQL's round() yields numeric, which psycopg hands over as Decimal; pydantic
    # would send that as a string, and the bar widths need a number.
    return float(value) if isinstance(value, Decimal) else jsonable(value)


def export_feedback(read, dashboard: dict, filters: PanelFilters) -> list[dict]:
    """The newest LIST_MAX_LIMIT ratings that match the filters, newest first, each with its
    labels and its conversation (or None)."""
    sql = dashboard["download"]["sql"].replace(FILTERS_MARKER, dashboard["filters"]["sql"])
    params = {**filters.params(), "limit": LIST_MAX_LIMIT}
    columns, rows = read.run_dashboard_sql(sql, params, QUERY_TIMEOUT_MS)
    ratings = [dict(zip(columns, (jsonable(v) for v in row), strict=True)) for row in rows]
    # Core gives every record a request_id, and a rating and its transcript are posted under
    # the same one, so a rating's conversation is the transcript with its request_id or none:
    # any looser match (the same session, say) could only attach another run's conversation,
    # such as when the user declined to store their own. App.jsx pairs the Query & table rows
    # by the same rule.
    transcripts = read.select_transcripts_by_request_ids(
        [r["request_id"] for r in ratings if r.get("request_id")]
    )
    conversations = {t.request_id: t.atif for t in map(row_to_transcript, transcripts)}
    return [
        {
            **Feedback(
                **r, name=display_name(r.get("skill_name"), r.get("session_id"))
            ).model_dump(),
            "conversation": conversations.get(r.get("request_id")),
        }
        for r in ratings
    ]
